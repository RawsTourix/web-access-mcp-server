from __future__ import annotations

import os

import pytest

from web_access.core.config import RedisSettings
from web_access.infrastructure.redis import RedisDependency

pytestmark = pytest.mark.integration


def _settings() -> RedisSettings:
    url = os.environ.get("WEB_ACCESS_TEST_REDIS_URL")
    if not url:
        pytest.fail("WEB_ACCESS_TEST_REDIS_URL is required for Redis integration tests")
    return RedisSettings.model_validate({"url": url, "socket_timeout_seconds": 0.5})


@pytest.mark.asyncio
async def test_redis_lifecycle_ping_and_no_side_effects() -> None:
    dependency = RedisDependency(_settings())
    assert not await dependency.ping()
    await dependency.start()
    assert await dependency.ping()
    assert await dependency.client.dbsize() == 0
    await dependency.client.connection_pool.disconnect()
    assert await dependency.ping()
    await dependency.close()
    assert not await dependency.ping()
    await dependency.close()


@pytest.mark.asyncio
async def test_new_dependency_recovers_after_unavailable_endpoint() -> None:
    unavailable = RedisDependency(
        RedisSettings.model_validate(
            {"url": "redis://127.0.0.1:56378/0", "socket_timeout_seconds": 0.1}
        )
    )
    await unavailable.start()
    assert not await unavailable.ping()
    await unavailable.close()

    recovered = RedisDependency(_settings())
    await recovered.start()
    assert await recovered.ping()
    await recovered.close()
