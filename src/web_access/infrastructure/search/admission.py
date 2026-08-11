"""Independent Redis rate and provider concurrency admission mechanisms."""

# ruff: noqa: S105 -- token-bucket names and Lua source are protocol data, not secrets.

from __future__ import annotations

import asyncio
import hashlib
import inspect
import secrets
from dataclasses import dataclass
from time import monotonic
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from web_access.application.common.health import Availability
from web_access.application.search.ports import (
    ConcurrencyLease,
    RateAdmission,
    RateAdmissionStatus,
)
from web_access.domain.search import SearchProviderId

TOKEN_BUCKET_SCRIPT_REVISION = "3"
CONCURRENCY_ACQUIRE_SCRIPT_REVISION = "3"
CONCURRENCY_RELEASE_SCRIPT_REVISION = "1"
FLOW_GENERATION_REVISION = "2"

_TOKEN_BUCKET = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local server_info = redis.call('INFO', 'server')
local run_id = string.match(server_info, 'run_id:([^\\r\\n]+)')
if not run_id then
  return redis.error_reply('Redis server run_id is unavailable')
end

local generation = redis.call('HGET', KEYS[3], 'generation')
local marker_run_id = redis.call('HGET', KEYS[3], 'run_id')
local quarantine_until = tonumber(redis.call('HGET', KEYS[3], 'quarantine_until_ms')) or 0
if not generation then
  generation = ARGV[8]
  quarantine_until = now_ms + tonumber(ARGV[7])
  redis.call('HSET', KEYS[3], 'generation', generation, 'run_id', run_id,
    'quarantine_until_ms', quarantine_until)
elseif marker_run_id ~= run_id then
  generation = ARGV[8]
  quarantine_until = now_ms + tonumber(ARGV[7])
  redis.call('HSET', KEYS[3], 'generation', generation, 'run_id', run_id,
    'quarantine_until_ms', quarantine_until)
end
if quarantine_until > now_ms then
  return {2, quarantine_until - now_ms, generation}
end

local function state(key, capacity, refill)
  local values = redis.call('HMGET', key, 'tokens', 'updated_ms')
  local tokens = tonumber(values[1]) or capacity
  local updated = tonumber(values[2]) or now_ms
  local elapsed = math.max(0, now_ms - updated) / 1000
  return math.min(capacity, tokens + elapsed * refill)
end

local principal_capacity = tonumber(ARGV[1])
local principal_refill = tonumber(ARGV[2])
local global_capacity = tonumber(ARGV[3])
local global_refill = tonumber(ARGV[4])
local cost = tonumber(ARGV[5])
local ttl_ms = tonumber(ARGV[6])

local principal_tokens = state(KEYS[1], principal_capacity, principal_refill)
local global_tokens = state(KEYS[2], global_capacity, global_refill)

if principal_tokens < cost or global_tokens < cost then
  local principal_wait = 0
  local global_wait = 0
  if principal_tokens < cost then
    principal_wait = (cost - principal_tokens) / principal_refill
  end
  if global_tokens < cost then
    global_wait = (cost - global_tokens) / global_refill
  end
  return {0, math.ceil(math.max(principal_wait, global_wait) * 1000), generation}
end

redis.call('HSET', KEYS[1], 'tokens', principal_tokens - cost, 'updated_ms', now_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
redis.call('HSET', KEYS[2], 'tokens', global_tokens - cost, 'updated_ms', now_ms)
redis.call('PEXPIRE', KEYS[2], ttl_ms)
return {1, 0, generation}
"""

_CONCURRENCY_ACQUIRE = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local server_info = redis.call('INFO', 'server')
local run_id = string.match(server_info, 'run_id:([^\\r\\n]+)')
if not run_id then
  return redis.error_reply('Redis server run_id is unavailable')
end
local generation = redis.call('HGET', KEYS[2], 'generation')
local marker_run_id = redis.call('HGET', KEYS[2], 'run_id')
local quarantine_until = tonumber(redis.call('HGET', KEYS[2], 'quarantine_until_ms')) or 0
if not generation then
  generation = ARGV[5]
  quarantine_until = now_ms + tonumber(ARGV[4])
  redis.call('HSET', KEYS[2], 'generation', generation, 'run_id', run_id,
    'quarantine_until_ms', quarantine_until)
elseif marker_run_id ~= run_id then
  generation = ARGV[5]
  quarantine_until = now_ms + tonumber(ARGV[4])
  redis.call('HSET', KEYS[2], 'generation', generation, 'run_id', run_id,
    'quarantine_until_ms', quarantine_until)
end
if quarantine_until > now_ms then
  return {2, generation}
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
  return {0, generation}
end
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[2]), ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) * 2)
return {1, generation}
"""

_CONCURRENCY_RELEASE = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""

_FLOW_READINESS = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
local server_info = redis.call('INFO', 'server')
local run_id = string.match(server_info, 'run_id:([^\\r\\n]+)')
if not run_id then
  return 0
end
local values = redis.call('HMGET', KEYS[1], 'generation', 'run_id', 'quarantine_until_ms')
if not values[1] or values[2] ~= run_id then
  return 0
end
local quarantine_until = tonumber(values[3])
if not quarantine_until or quarantine_until > now_ms then
  return 0
end
return 1
"""


async def _redis_result(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass(frozen=True, slots=True)
class TokenBucketPolicy:
    capacity: int
    refill_per_second: float

    def __post_init__(self) -> None:
        if self.capacity < 1 or self.refill_per_second <= 0:
            raise ValueError("invalid token bucket policy")


@dataclass(frozen=True, slots=True)
class ProviderRatePolicy:
    principal: TokenBucketPolicy
    global_: TokenBucketPolicy


class RedisProviderRateLimiter:
    def __init__(
        self,
        client: Redis,
        *,
        namespace: str,
        policies: dict[SearchProviderId, ProviderRatePolicy],
        state_loss_horizons: dict[SearchProviderId, float] | None = None,
    ) -> None:
        self._client = client
        self._prefix = f"{namespace}:search-rate:v{TOKEN_BUCKET_SCRIPT_REVISION}:"
        self._generation_prefix = f"{namespace}:search-flow-generation:v{FLOW_GENERATION_REVISION}:"
        self._policies = dict(policies)
        self._state_loss_horizons = dict(state_loss_horizons or {})

    def keys(self, principal_id: str, provider_id: SearchProviderId) -> tuple[str, str]:
        principal_hash = hashlib.sha256(principal_id.encode()).hexdigest()
        tag = f"{{{provider_id.value}}}"
        return (
            f"{self._prefix}{tag}:principal:{principal_hash}",
            f"{self._prefix}{tag}:global",
        )

    def generation_key(self, provider_id: SearchProviderId) -> str:
        return f"{self._generation_prefix}{{{provider_id.value}}}"

    async def admit(
        self,
        *,
        principal_id: str,
        provider_id: SearchProviderId,
        wait_seconds: float | None,
    ) -> RateAdmission:
        _ = wait_seconds
        policy = self._policies.get(provider_id)
        if policy is None:
            return RateAdmission(RateAdmissionStatus.UNAVAILABLE)
        try:
            policy_horizon = max(
                policy.principal.capacity / policy.principal.refill_per_second,
                policy.global_.capacity / policy.global_.refill_per_second,
            )
            horizon = max(policy_horizon, self._state_loss_horizons.get(provider_id, 0))
            ttl_ms = max(
                1000,
                round(
                    2000
                    * max(
                        policy.principal.capacity / policy.principal.refill_per_second,
                        policy.global_.capacity / policy.global_.refill_per_second,
                    )
                ),
            )
            result = await _redis_result(
                self._client.eval(
                    _TOKEN_BUCKET,
                    3,
                    *self.keys(principal_id, provider_id),
                    self.generation_key(provider_id),
                    policy.principal.capacity,
                    policy.principal.refill_per_second,
                    policy.global_.capacity,
                    policy.global_.refill_per_second,
                    1,
                    ttl_ms,
                    max(1, round(horizon * 1000)),
                    secrets.token_hex(16),
                )
            )
        except RedisError:
            return RateAdmission(RateAdmissionStatus.UNAVAILABLE)
        if not isinstance(result, (list, tuple)) or len(result) != 3:
            return RateAdmission(RateAdmissionStatus.UNAVAILABLE)
        _text_result(result[2])
        status = int(result[0])
        if status == 1:
            return RateAdmission(RateAdmissionStatus.ALLOWED)
        retry_after = int(result[1]) / 1000 or None
        if status == 0:
            return RateAdmission(RateAdmissionStatus.RATE_LIMITED, retry_after)
        return RateAdmission(RateAdmissionStatus.UNAVAILABLE, retry_after)


@dataclass(frozen=True, slots=True)
class ProviderConcurrencyPolicy:
    local_limit: int
    global_limit: int
    lease_seconds: float
    admission_timeout_seconds: float

    def __post_init__(self) -> None:
        if (
            min(
                self.local_limit,
                self.global_limit,
                self.lease_seconds,
                self.admission_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("invalid provider concurrency policy")


class RedisProviderConcurrencyLimiter:
    def __init__(
        self,
        client: Redis,
        *,
        namespace: str,
        policies: dict[SearchProviderId, ProviderConcurrencyPolicy],
        poll_seconds: float = 0.01,
        state_loss_horizons: dict[SearchProviderId, float] | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("concurrency poll interval must be positive")
        self._client = client
        self._prefix = f"{namespace}:search-concurrency:v1:"
        self._generation_prefix = f"{namespace}:search-flow-generation:v{FLOW_GENERATION_REVISION}:"
        self._policies = dict(policies)
        self._local = {
            provider_id: asyncio.Semaphore(policy.local_limit)
            for provider_id, policy in policies.items()
        }
        self._owned: dict[str, SearchProviderId] = {}
        self._poll = poll_seconds
        self._state_loss_horizons = dict(state_loss_horizons or {})

    def key(self, provider_id: SearchProviderId) -> str:
        return f"{self._prefix}{{{provider_id.value}}}"

    def generation_key(self, provider_id: SearchProviderId) -> str:
        return f"{self._generation_prefix}{{{provider_id.value}}}"

    async def acquire(
        self, provider_id: SearchProviderId, *, wait_seconds: float | None
    ) -> ConcurrencyLease | None:
        policy = self._policies.get(provider_id)
        semaphore = self._local.get(provider_id)
        if policy is None or semaphore is None:
            return None
        timeout = policy.admission_timeout_seconds
        if wait_seconds is not None:
            timeout = min(timeout, max(0, wait_seconds))
        deadline = monotonic() + timeout
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=max(0, deadline - monotonic()))
        except TimeoutError:
            return None
        token = secrets.token_hex(16)
        try:
            while True:
                try:
                    horizon = max(
                        policy.lease_seconds,
                        self._state_loss_horizons.get(provider_id, 0),
                    )
                    acquired = await _redis_result(
                        self._client.eval(
                            _CONCURRENCY_ACQUIRE,
                            2,
                            self.key(provider_id),
                            self.generation_key(provider_id),
                            policy.global_limit,
                            max(1, round(policy.lease_seconds * 1000)),
                            token,
                            max(1, round(horizon * 1000)),
                            secrets.token_hex(16),
                        )
                    )
                    if not isinstance(acquired, (list, tuple)) or len(acquired) != 2:
                        return None
                    _text_result(acquired[1])
                    if int(acquired[0]) == 1:
                        self._owned[token] = provider_id
                        return ConcurrencyLease(provider_id, token)
                except RedisError:
                    return None
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                await asyncio.sleep(min(self._poll, remaining))
        finally:
            if token not in self._owned:
                semaphore.release()

    async def release(self, lease: ConcurrencyLease) -> None:
        provider_id = self._owned.pop(lease.token, None)
        if provider_id is None or provider_id is not lease.provider_id:
            return
        try:
            await _redis_result(
                self._client.eval(_CONCURRENCY_RELEASE, 1, self.key(provider_id), lease.token)
            )
        except RedisError:
            pass
        self._local[provider_id].release()


class RedisProviderFlowControlReadiness:
    """Read the shared generation quarantine without reserving flow-control capacity."""

    def __init__(self, client: Redis, *, namespace: str) -> None:
        self._client = client
        self._generation_prefix = f"{namespace}:search-flow-generation:v{FLOW_GENERATION_REVISION}:"

    def generation_key(self, provider_id: SearchProviderId) -> str:
        return f"{self._generation_prefix}{{{provider_id.value}}}"

    async def check(self, provider_id: SearchProviderId) -> Availability:
        try:
            result = await _redis_result(
                self._client.eval(
                    _FLOW_READINESS,
                    1,
                    self.generation_key(provider_id),
                )
            )
        except RedisError:
            return Availability.UNAVAILABLE
        return Availability.READY if result == 1 else Availability.UNAVAILABLE


def _text_result(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii")
    if isinstance(value, str):
        return value
    raise RedisError("Redis flow-control generation is malformed")
