"""S5 real Redis cache, privacy, TTL, and single-flight gates."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from web_access.application.search.models import (
    CacheMetadata,
    PaginationMetadata,
    SearchQueryData,
)
from web_access.application.search.ports import CacheLookupState, SingleFlightLease
from web_access.domain.search import SearchProviderId, SearchResultItem
from web_access.infrastructure.search.cache import RedisSearchCache, RedisSearchSingleFlight


def redis_url() -> str:
    value = os.getenv("WEB_ACCESS_TEST_REDIS_URL")
    if value is None:
        pytest.fail("WEB_ACCESS_TEST_REDIS_URL is required for Search cache integration tests")
    return value


def identity(query: str = "private query") -> str:
    return f"search:v1:{hashlib.sha256(query.encode()).hexdigest()}"


def data(*, cached: bool = False) -> SearchQueryData:
    retrieved_at = datetime(2026, 1, 1, tzinfo=UTC)
    return SearchQueryData(
        query="private query",
        provider_id=SearchProviderId.SEARXNG,
        page=1,
        requested_limit=10,
        results=(SearchResultItem(rank=1, title="title", url="https://example.test"),),
        cache=CacheMetadata(cached=cached, retrieved_at=retrieved_at),
        pagination=PaginationMetadata(page=1, next_page_available=None),
    )


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url())
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.mark.integration
async def test_cache_roundtrip_ttl_corruption_and_no_raw_query(redis_client: Redis) -> None:
    cache = RedisSearchCache(redis_client, namespace="test-web-access")
    cache_identity = identity()
    assert (await cache.get(cache_identity)).state is CacheLookupState.MISS
    assert await cache.put(cache_identity, data(), 30)
    lookup = await cache.get(cache_identity)
    assert lookup.state is CacheLookupState.HIT and lookup.value == data()
    key = cache.key(cache_identity)
    assert 0 < await redis_client.ttl(key) <= 30
    assert "private query" not in key
    assert "private query" not in "".join(
        item.decode() if isinstance(item, bytes) else str(item)
        for item in await redis_client.keys("*")
    )

    await redis_client.set(key, b"not-json", ex=30)
    assert (await cache.get(cache_identity)).state is CacheLookupState.CORRUPT
    assert await redis_client.get(key) is None


@pytest.mark.integration
async def test_cache_expiry_is_redis_owned(redis_client: Redis) -> None:
    cache = RedisSearchCache(redis_client, namespace="test-web-access")
    assert await cache.put(identity(), data(), 1)
    deadline = asyncio.get_running_loop().time() + 2
    while (await cache.get(identity())).state is CacheLookupState.HIT:
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("Redis cache key did not expire by deadline")
        await asyncio.sleep(0.01)
    assert (await cache.get(identity())).state is CacheLookupState.MISS


@pytest.mark.integration
async def test_single_flight_only_one_holder_and_owner_only_release(
    redis_client: Redis,
) -> None:
    flight = RedisSearchSingleFlight(
        redis_client,
        namespace="test-web-access",
        lease_seconds=1,
        poll_seconds=0.01,
    )
    cache_identity = identity()
    holder = await flight.acquire(cache_identity, wait_seconds=0.1)
    assert holder.holder and holder.token
    waiter = asyncio.create_task(flight.acquire(cache_identity, wait_seconds=1.5))

    wrong = SingleFlightLease(identity=cache_identity, holder=True, token="wrong-owner")
    await flight.release(wrong)
    assert await redis_client.get(flight.key(cache_identity)) == holder.token.encode()

    await flight.release(holder)
    promoted = await waiter
    assert promoted.holder and promoted.token != holder.token
    await flight.release(promoted)


@pytest.mark.integration
async def test_single_flight_holder_death_recovers_by_redis_ttl(redis_client: Redis) -> None:
    flight = RedisSearchSingleFlight(
        redis_client,
        namespace="test-web-access",
        lease_seconds=0.1,
        poll_seconds=0.005,
    )
    cache_identity = identity()
    abandoned = await flight.acquire(cache_identity, wait_seconds=0.05)
    assert abandoned.holder
    recovered = await flight.acquire(cache_identity, wait_seconds=1)
    assert recovered.holder and recovered.token != abandoned.token
    await flight.release(recovered)


@pytest.mark.integration
async def test_single_flight_wait_is_bounded_and_cancellable(redis_client: Redis) -> None:
    flight = RedisSearchSingleFlight(
        redis_client,
        namespace="test-web-access",
        lease_seconds=5,
        poll_seconds=0.01,
    )
    cache_identity = identity()
    holder = await flight.acquire(cache_identity, wait_seconds=0.1)
    rejected = await flight.acquire(cache_identity, wait_seconds=0.03)
    assert not rejected.holder
    waiting = asyncio.create_task(flight.acquire(cache_identity, wait_seconds=5))
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await flight.release(holder)
