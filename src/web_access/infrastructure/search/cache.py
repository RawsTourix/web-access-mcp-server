"""Redis Search cache and narrowly-scoped single-flight coordination."""

from __future__ import annotations

import asyncio
import inspect
import secrets
from time import monotonic

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from web_access.application.search.models import SearchQueryData
from web_access.application.search.ports import (
    CacheLookup,
    CacheLookupState,
    SingleFlightLease,
)

CACHE_SCHEMA_REVISION = "1"
SINGLE_FLIGHT_RELEASE_SCRIPT_REVISION = "1"

_RELEASE_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisSearchCache:
    def __init__(self, client: Redis, *, namespace: str) -> None:
        self._client = client
        self._prefix = f"{namespace}:search-cache:v{CACHE_SCHEMA_REVISION}:"

    def key(self, identity: str) -> str:
        if not identity.startswith("search:v1:") or len(identity) != 74:
            raise ValueError("invalid hashed Search cache identity")
        return f"{self._prefix}{identity.removeprefix('search:v1:')}"

    async def get(self, identity: str) -> CacheLookup:
        key = self.key(identity)
        try:
            payload = await self._client.get(key)
        except RedisError:
            return CacheLookup(CacheLookupState.UNAVAILABLE)
        if payload is None:
            return CacheLookup(CacheLookupState.MISS)
        try:
            return CacheLookup(CacheLookupState.HIT, SearchQueryData.model_validate_json(payload))
        except (ValidationError, ValueError, TypeError):
            try:
                await self._client.delete(key)
            except RedisError:
                pass
            return CacheLookup(CacheLookupState.CORRUPT)

    async def put(self, identity: str, value: SearchQueryData, ttl_seconds: int) -> bool:
        if ttl_seconds < 1:
            raise ValueError("Search cache TTL must be positive")
        try:
            return bool(
                await self._client.set(self.key(identity), value.model_dump_json(), ex=ttl_seconds)
            )
        except RedisError:
            return False


class RedisSearchSingleFlight:
    def __init__(
        self,
        client: Redis,
        *,
        namespace: str,
        lease_seconds: float,
        poll_seconds: float,
    ) -> None:
        if lease_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("single-flight timing must be positive")
        self._client = client
        self._prefix = f"{namespace}:search-flight:v1:"
        self._lease_ms = max(1, round(lease_seconds * 1000))
        self._poll = poll_seconds

    def key(self, identity: str) -> str:
        if not identity.startswith("search:v1:") or len(identity) != 74:
            raise ValueError("invalid hashed Search single-flight identity")
        return f"{self._prefix}{identity.removeprefix('search:v1:')}"

    async def acquire(self, identity: str, *, wait_seconds: float | None) -> SingleFlightLease:
        key = self.key(identity)
        token = secrets.token_hex(16)
        deadline = None if wait_seconds is None else monotonic() + max(0, wait_seconds)
        while True:
            try:
                acquired = await self._client.set(key, token, nx=True, px=self._lease_ms)
            except RedisError:
                # Cache coordination may degrade, but application admission/accounting still runs.
                return SingleFlightLease(identity=identity, holder=True, token=None)
            if acquired:
                return SingleFlightLease(identity=identity, holder=True, token=token)
            if deadline is not None and monotonic() >= deadline:
                return SingleFlightLease(identity=identity, holder=False)
            remaining = self._poll if deadline is None else min(self._poll, deadline - monotonic())
            if remaining <= 0:
                return SingleFlightLease(identity=identity, holder=False)
            await asyncio.sleep(remaining)

    async def release(self, lease: SingleFlightLease) -> None:
        if not lease.holder or lease.token is None:
            return
        try:
            result = self._client.eval(_RELEASE_IF_OWNER, 1, self.key(lease.identity), lease.token)
            if inspect.isawaitable(result):
                await result
        except RedisError:
            # Lease expiry remains the crash/restart recovery path.
            return
