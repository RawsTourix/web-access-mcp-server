"""S6 real Redis token-bucket and distributed concurrency race gates."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from web_access.application.search.ports import (
    ConcurrencyLease,
    RateAdmissionStatus,
)
from web_access.domain.search import SearchProviderId
from web_access.infrastructure.search.admission import (
    ProviderConcurrencyPolicy,
    ProviderRatePolicy,
    RedisProviderConcurrencyLimiter,
    RedisProviderRateLimiter,
    TokenBucketPolicy,
)


def redis_url() -> str:
    value = os.getenv("WEB_ACCESS_TEST_REDIS_URL")
    if value is None:
        pytest.fail("WEB_ACCESS_TEST_REDIS_URL is required for Search admission tests")
    return value


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url())
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


def rate_limiter(
    client: Redis,
    *,
    principal_capacity: int,
    global_capacity: int,
    principal_refill: float = 0.001,
    global_refill: float = 0.001,
) -> RedisProviderRateLimiter:
    return RedisProviderRateLimiter(
        client,
        namespace="test-web-access",
        policies={
            SearchProviderId.SEARXNG: ProviderRatePolicy(
                principal=TokenBucketPolicy(principal_capacity, principal_refill),
                global_=TokenBucketPolicy(global_capacity, global_refill),
            )
        },
    )


@pytest.mark.integration
async def test_token_bucket_burst_boundary_retry_after_and_no_raw_principal(
    redis_client: Redis,
) -> None:
    limiter = rate_limiter(redis_client, principal_capacity=2, global_capacity=2)
    first = await limiter.admit(
        principal_id="private-principal",
        provider_id=SearchProviderId.SEARXNG,
        wait_seconds=1,
    )
    second = await limiter.admit(
        principal_id="private-principal",
        provider_id=SearchProviderId.SEARXNG,
        wait_seconds=1,
    )
    denied = await limiter.admit(
        principal_id="private-principal",
        provider_id=SearchProviderId.SEARXNG,
        wait_seconds=1,
    )
    assert first.allowed and second.allowed and not denied.allowed
    assert denied.retry_after_seconds and denied.retry_after_seconds > 0
    visible_keys = "".join(limiter.keys("private-principal", SearchProviderId.SEARXNG))
    assert "private-principal" not in visible_keys


@pytest.mark.integration
async def test_principal_and_global_reservation_is_atomic(redis_client: Redis) -> None:
    limiter = rate_limiter(
        redis_client,
        principal_capacity=1,
        global_capacity=1,
        principal_refill=0.001,
        global_refill=10,
    )
    assert (
        await limiter.admit(
            principal_id="one", provider_id=SearchProviderId.SEARXNG, wait_seconds=1
        )
    ).allowed
    denied = await limiter.admit(
        principal_id="two", provider_id=SearchProviderId.SEARXNG, wait_seconds=1
    )
    assert not denied.allowed
    principal_two, _ = limiter.keys("two", SearchProviderId.SEARXNG)
    assert not await redis_client.exists(principal_two)
    deadline = asyncio.get_running_loop().time() + 1
    while True:
        admitted = await limiter.admit(
            principal_id="two", provider_id=SearchProviderId.SEARXNG, wait_seconds=1
        )
        if admitted.allowed:
            break
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("global token did not refill by deadline")
        await asyncio.sleep(0)


@pytest.mark.integration
async def test_exact_last_token_race_has_no_overspend(redis_client: Redis) -> None:
    for iteration in range(10):
        await redis_client.flushdb()
        limiter = rate_limiter(redis_client, principal_capacity=5, global_capacity=5)
        admissions = await asyncio.gather(
            *(
                limiter.admit(
                    principal_id=f"race-{iteration}",
                    provider_id=SearchProviderId.SEARXNG,
                    wait_seconds=1,
                )
                for _ in range(30)
            )
        )
        assert sum(item.allowed for item in admissions) == 5, iteration


def concurrency_limiter(
    client: Redis, *, global_limit: int = 2, lease_seconds: float = 1
) -> RedisProviderConcurrencyLimiter:
    return RedisProviderConcurrencyLimiter(
        client,
        namespace="test-web-access",
        policies={
            SearchProviderId.SEARXNG: ProviderConcurrencyPolicy(
                local_limit=10,
                global_limit=global_limit,
                lease_seconds=lease_seconds,
                admission_timeout_seconds=0.2,
            )
        },
        poll_seconds=0.005,
    )


@pytest.mark.integration
async def test_global_concurrency_cap_across_replicas_and_wrong_owner(
    redis_client: Redis,
) -> None:
    first_replica = concurrency_limiter(redis_client)
    second_replica = concurrency_limiter(redis_client)
    one = await first_replica.acquire(SearchProviderId.SEARXNG, wait_seconds=0.1)
    two = await second_replica.acquire(SearchProviderId.SEARXNG, wait_seconds=0.1)
    assert one and two
    denied = await second_replica.acquire(SearchProviderId.SEARXNG, wait_seconds=0.02)
    assert denied is None
    await first_replica.release(ConcurrencyLease(SearchProviderId.SEARXNG, "wrong-owner-token"))
    assert await redis_client.zcard(first_replica.key(SearchProviderId.SEARXNG)) == 2
    await first_replica.release(one)
    promoted = await second_replica.acquire(SearchProviderId.SEARXNG, wait_seconds=0.1)
    assert promoted is not None
    await second_replica.release(two)
    await second_replica.release(promoted)


@pytest.mark.integration
async def test_crashed_concurrency_holder_expires_and_cancel_releases_local(
    redis_client: Redis,
) -> None:
    crashed = concurrency_limiter(redis_client, global_limit=1, lease_seconds=0.1)
    survivor = concurrency_limiter(redis_client, global_limit=1, lease_seconds=0.1)
    abandoned = await crashed.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)
    assert abandoned is not None
    recovered = await survivor.acquire(SearchProviderId.SEARXNG, wait_seconds=0.3)
    assert recovered is not None
    await survivor.release(recovered)

    holder = await crashed.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)
    assert holder is not None
    waiting = asyncio.create_task(crashed.acquire(SearchProviderId.SEARXNG, wait_seconds=1))
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await crashed.release(holder)
    final = await crashed.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)
    assert final is not None
    await crashed.release(final)


@pytest.mark.integration
async def test_admission_fails_closed_when_redis_is_unavailable() -> None:
    unavailable = Redis.from_url(
        "redis://127.0.0.1:56378/0", socket_connect_timeout=0.05, socket_timeout=0.05
    )
    try:
        rate = rate_limiter(unavailable, principal_capacity=1, global_capacity=1)
        admission = await rate.admit(
            principal_id="p", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1
        )
        assert admission.status is RateAdmissionStatus.UNAVAILABLE
        concurrency = concurrency_limiter(unavailable, global_limit=1)
        assert (await concurrency.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)) is None
    finally:
        await unavailable.aclose()


@pytest.mark.integration
async def test_rate_flushdb_is_detected_by_two_replicas_and_recovers_after_horizon(
    redis_client: Redis,
) -> None:
    first = rate_limiter(
        redis_client,
        principal_capacity=1,
        global_capacity=1,
        principal_refill=20,
        global_refill=20,
    )
    second = rate_limiter(
        redis_client,
        principal_capacity=1,
        global_capacity=1,
        principal_refill=20,
        global_refill=20,
    )
    assert (
        await first.admit(
            principal_id="flush", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1
        )
    ).allowed
    assert not (
        await second.admit(
            principal_id="flush", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1
        )
    ).allowed

    await redis_client.flushdb()
    after_flush = await asyncio.gather(
        first.admit(principal_id="flush", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1),
        second.admit(principal_id="flush", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1),
    )
    assert all(item.status is RateAdmissionStatus.UNAVAILABLE for item in after_flush)
    await asyncio.sleep(0.06)
    recovered = await first.admit(
        principal_id="flush", provider_id=SearchProviderId.SEARXNG, wait_seconds=0.1
    )
    assert recovered.status is RateAdmissionStatus.ALLOWED


@pytest.mark.integration
async def test_concurrency_flushdb_does_not_reopen_capacity_before_lease_horizon(
    redis_client: Redis,
) -> None:
    first = concurrency_limiter(redis_client, global_limit=1, lease_seconds=0.15)
    second = concurrency_limiter(redis_client, global_limit=1, lease_seconds=0.15)
    live = await first.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)
    assert live is not None
    assert await second.acquire(SearchProviderId.SEARXNG, wait_seconds=0.02) is None

    await redis_client.flushdb()
    assert await second.acquire(SearchProviderId.SEARXNG, wait_seconds=0.02) is None
    await asyncio.sleep(0.16)
    recovered = await second.acquire(SearchProviderId.SEARXNG, wait_seconds=0.05)
    assert recovered is not None
    await first.release(live)
    await second.release(recovered)
