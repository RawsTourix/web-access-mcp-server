"""Owned Redis asyncio client lifecycle and non-mutating health probe."""

from __future__ import annotations

import inspect

from redis.asyncio import Redis

from web_access.core.config import RedisSettings


class RedisDependency:
    """Minimal lifecycle wrapper; no cache, queue, lock, or durable semantics."""

    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis dependency has not been started")
        return self._client

    async def start(self) -> None:
        if self._client is not None:
            return
        self._client = Redis.from_url(
            str(self._settings.url),
            socket_timeout=self._settings.socket_timeout_seconds,
            socket_connect_timeout=self._settings.socket_timeout_seconds,
            health_check_interval=30,
        )

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            result = self._client.ping()
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:  # Infrastructure boundary normalizes concrete Redis failures.
            return False

    async def close(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        await client.aclose()

    async def __aenter__(self) -> RedisDependency:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


def create_redis_dependency(settings: RedisSettings) -> RedisDependency:
    return RedisDependency(settings)
