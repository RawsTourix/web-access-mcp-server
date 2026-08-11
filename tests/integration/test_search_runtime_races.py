"""S15 multi-instance Search race and backpressure gates against real Redis."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable
from datetime import UTC, datetime
from typing import cast

import pytest
from redis.asyncio import Redis

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.results import LeafOutcome, OperationOutcome
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
    SearchBatchRequest,
    SearchQuery,
)
from web_access.application.search.registry import SearchProviderRegistry, SearchRegionRegistry
from web_access.application.search.service import SearchApplicationService, SearchServicePolicy
from web_access.core.time import Deadline, SystemClock
from web_access.domain.search import SearchProviderId, SearchResultItem
from web_access.infrastructure.search import (
    ProviderConcurrencyPolicy,
    ProviderRatePolicy,
    RedisProviderConcurrencyLimiter,
    RedisProviderRateLimiter,
    RedisSearchCache,
    RedisSearchSingleFlight,
    TokenBucketPolicy,
)

pytestmark = pytest.mark.integration


def _redis_url() -> str:
    value = os.getenv("WEB_ACCESS_TEST_REDIS_URL")
    if value is None:
        pytest.fail("WEB_ACCESS_TEST_REDIS_URL is required for Search race tests")
    return value


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(_redis_url())
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


async def _trust_flow_state(client: Redis, *, namespace: str) -> None:
    info = await client.info(section="server")
    await cast(
        Awaitable[int],
        client.hset(
            f"{namespace}:search-flow-generation:v2:{{searxng}}",
            mapping={
                "generation": "known-safe-test-state",
                "run_id": info["run_id"],
                "quarantine_until_ms": "0",
            },
        ),
    )


class ControlledProvider:
    def __init__(self, *, delay_seconds: float) -> None:
        self.descriptor = ProviderDescriptor(
            provider_id=SearchProviderId.SEARXNG,
            name="controlled-searxng",
            enabled=True,
            configuration_revision="controlled-searxng-v1",
            capabilities=ProviderCapabilities(
                pagination=True,
                language=True,
                region=False,
                safe_search=True,
                time_range=True,
                max_results=50,
                billable=False,
            ),
        )
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = context
        async with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay_seconds)
            return ProviderSearchResult(
                provider_id=SearchProviderId.SEARXNG,
                results=(
                    SearchResultItem(
                        rank=1,
                        title=request.query,
                        url="https://example.test/result",
                    ),
                ),
                retrieved_at=datetime.now(UTC),
            )
        finally:
            async with self._lock:
                self.active -= 1


def _service(
    client: Redis,
    provider: ControlledProvider,
    *,
    namespace: str,
    local_limit: int = 4,
    global_limit: int = 4,
    admission_timeout_seconds: float = 0.5,
) -> SearchApplicationService:
    return SearchApplicationService(
        providers=SearchProviderRegistry((provider,), default_provider=SearchProviderId.SEARXNG),
        regions=SearchRegionRegistry(()),
        cache=RedisSearchCache(client, namespace=namespace),
        single_flight=RedisSearchSingleFlight(
            client,
            namespace=namespace,
            lease_seconds=2,
            poll_seconds=0.002,
        ),
        rate_limiter=RedisProviderRateLimiter(
            client,
            namespace=namespace,
            policies={
                SearchProviderId.SEARXNG: ProviderRatePolicy(
                    principal=TokenBucketPolicy(1000, 1000),
                    global_=TokenBucketPolicy(1000, 1000),
                )
            },
        ),
        concurrency_limiter=RedisProviderConcurrencyLimiter(
            client,
            namespace=namespace,
            policies={
                SearchProviderId.SEARXNG: ProviderConcurrencyPolicy(
                    local_limit=local_limit,
                    global_limit=global_limit,
                    lease_seconds=2,
                    admission_timeout_seconds=admission_timeout_seconds,
                )
            },
            poll_seconds=0.002,
        ),
        usage_uow_factory=None,
        policy=SearchServicePolicy(searxng_max_attempts=1),
    )


def _context(operation_id: str) -> ExecutionContext:
    clock = SystemClock()
    return ExecutionContext(
        operation_id=operation_id,
        principal=PrincipalContext("race-principal", frozenset({"search:read"})),
        clock=clock,
        cancellation=CancellationToken(),
        deadline=Deadline.after(clock, 5),
    )


@pytest.mark.asyncio
async def test_identical_requests_across_instances_have_one_call_and_fresh_cache(
    redis_client: Redis,
) -> None:
    provider = ControlledProvider(delay_seconds=0.05)
    await _trust_flow_state(redis_client, namespace="race-identical")
    first = _service(redis_client, provider, namespace="race-identical")
    second = _service(redis_client, provider, namespace="race-identical")
    request = SearchBatchRequest(queries=(SearchQuery(query="same query"),))

    results = await asyncio.gather(
        first.search(_context("op_first"), request),
        second.search(_context("op_second"), request),
    )

    assert provider.calls == 1
    assert all(result.outcome is OperationOutcome.SUCCEEDED for result in results)
    data = [result.data.items[0].data for result in results if result.data]
    assert all(item is not None for item in data)
    concrete = [item for item in data if item is not None]
    assert sorted(item.cache.cached for item in concrete) == [False, True]
    assert concrete[0].cache.retrieved_at == concrete[1].cache.retrieved_at
    assert [item.query for item in concrete] == ["same query", "same query"]


@pytest.mark.asyncio
async def test_many_clients_obey_cross_instance_global_cap_and_backpressure(
    redis_client: Redis,
) -> None:
    for seed in range(5):
        await redis_client.flushdb()
        provider = ControlledProvider(delay_seconds=0.08)
        namespace = f"race-load-{seed}"
        await _trust_flow_state(redis_client, namespace=namespace)
        replicas = (
            _service(
                redis_client,
                provider,
                namespace=namespace,
                local_limit=2,
                global_limit=3,
                admission_timeout_seconds=0.02,
            ),
            _service(
                redis_client,
                provider,
                namespace=namespace,
                local_limit=2,
                global_limit=3,
                admission_timeout_seconds=0.02,
            ),
        )
        results = await asyncio.gather(
            *(
                replicas[index % 2].search(
                    _context(f"op_{seed}_{index}"),
                    SearchBatchRequest(queries=(SearchQuery(query=f"query {seed} {index}"),)),
                )
                for index in range(20)
            )
        )
        outcomes = [result.data.items[0] for result in results if result.data]
        assert provider.max_active <= 3, seed
        assert provider.active == 0, seed
        assert any(item.outcome is LeafOutcome.SUCCEEDED for item in outcomes), seed
        rejected = [item for item in outcomes if item.outcome is LeafOutcome.FAILED]
        assert rejected, seed
        assert all(
            item.error is not None and item.error.code == "provider_capacity_unavailable"
            for item in rejected
        ), seed
