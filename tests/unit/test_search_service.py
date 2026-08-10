"""S4 SearchApplicationService orchestration gates with deterministic fakes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory, OperationError
from web_access.application.common.results import ExecutionStage, LeafOutcome, OperationOutcome
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
    SearchBatchRequest,
    SearchQuery,
    SearchQueryData,
)
from web_access.application.search.ports import (
    CacheLookup,
    CacheLookupState,
    ConcurrencyLease,
    ProviderAttemptError,
    RateAdmission,
    SearchUsageUnavailable,
    SearchUsageUnitOfWork,
    SingleFlightLease,
)
from web_access.application.search.registry import SearchProviderRegistry, SearchRegionRegistry
from web_access.application.search.service import SearchApplicationService, SearchServicePolicy
from web_access.core.time import Deadline, FakeClock
from web_access.domain.search import SearchProviderId, SearchProviderSelection, SearchResultItem

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeProvider:
    def __init__(
        self,
        provider_id: SearchProviderId,
        *,
        enabled: bool = True,
        billable: bool = False,
    ) -> None:
        self.descriptor = ProviderDescriptor(
            provider_id=provider_id,
            name=provider_id.value,
            enabled=enabled,
            configuration_revision=f"revision-{provider_id.value}",
            capabilities=ProviderCapabilities(
                pagination=True,
                language=True,
                region=False,
                safe_search=True,
                time_range=True,
                max_results=50,
                billable=billable,
            ),
        )
        self.calls: list[ProviderSearchRequest] = []
        self.failures: list[ProviderAttemptError] = []
        self.wait_event: asyncio.Event | None = None
        self.called_event = asyncio.Event()

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = context
        self.calls.append(request)
        self.called_event.set()
        if self.wait_event is not None:
            await self.wait_event.wait()
        if self.failures:
            raise self.failures.pop(0)
        return ProviderSearchResult(
            provider_id=self.descriptor.provider_id,
            results=(SearchResultItem(rank=1, title=request.query, url="https://example.test"),),
            retrieved_at=NOW,
            next_page_available=None,
        )


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, SearchQueryData] = {}
        self.write_ok = True
        self.gets = 0
        self.puts = 0

    async def get(self, identity: str) -> CacheLookup:
        self.gets += 1
        value = self.values.get(identity)
        if value is not None:
            return CacheLookup(CacheLookupState.HIT, value)
        return CacheLookup(CacheLookupState.MISS)

    async def put(self, identity: str, value: SearchQueryData, ttl_seconds: int) -> bool:
        _ = ttl_seconds
        self.puts += 1
        if self.write_ok:
            self.values[identity] = value
        return self.write_ok


class FakeSingleFlight:
    def __init__(self) -> None:
        self.releases = 0

    async def acquire(self, identity: str, *, wait_seconds: float | None) -> SingleFlightLease:
        _ = wait_seconds
        return SingleFlightLease(identity=identity, holder=True, token="holder")

    async def release(self, lease: SingleFlightLease) -> None:
        _ = lease
        self.releases += 1


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls: list[SearchProviderId] = []
        self.allowed = True

    async def admit(
        self, *, principal_id: str, provider_id: SearchProviderId, wait_seconds: float | None
    ) -> RateAdmission:
        _ = principal_id, wait_seconds
        self.calls.append(provider_id)
        return RateAdmission(self.allowed, None if self.allowed else 1)


class FakeConcurrencyLimiter:
    def __init__(self) -> None:
        self.acquires: list[SearchProviderId] = []
        self.releases = 0
        self.available = True

    async def acquire(
        self, provider_id: SearchProviderId, *, wait_seconds: float | None
    ) -> ConcurrencyLease | None:
        _ = wait_seconds
        self.acquires.append(provider_id)
        return ConcurrencyLease(provider_id, "slot") if self.available else None

    async def release(self, lease: ConcurrencyLease) -> None:
        _ = lease
        self.releases += 1


class FakeUsage:
    def __init__(self) -> None:
        self.starts: list[tuple[str, int]] = []
        self.stages: list[str] = []
        self.commits = 0

    def __call__(self) -> SearchUsageUnitOfWork:
        return self

    @property
    def usage(self) -> FakeUsage:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type, exc_value, traceback

    async def commit(self) -> None:
        self.commits += 1

    async def start_attempt(self, **values: object) -> None:
        attempt_number = values["attempt_number"]
        assert isinstance(attempt_number, int)
        self.starts.append((str(values["operation_id"]), attempt_number))

    async def mark_stage(self, **values: object) -> None:
        self.stages.append(str(values["stage"]))


class UnavailableUsage(FakeUsage):
    async def start_attempt(self, **values: object) -> None:
        _ = values
        raise SearchUsageUnavailable("database unavailable")


class CommitUnavailableUsage(FakeUsage):
    async def commit(self) -> None:
        raise SearchUsageUnavailable("commit unavailable")


def context(
    *,
    scopes: frozenset[str] = frozenset({"search:read"}),
    principal_id: str = "principal",
) -> ExecutionContext:
    clock = FakeClock(NOW)
    return ExecutionContext(
        operation_id="op_test",
        principal=PrincipalContext(principal_id, scopes),
        clock=clock,
        cancellation=CancellationToken(),
        deadline=Deadline.after(clock, 30),
    )


def build(
    *,
    default: SearchProviderId = SearchProviderId.SEARXNG,
    searxng: FakeProvider | None = None,
    yandex: FakeProvider | None = None,
    cache: FakeCache | None = None,
    policy: SearchServicePolicy | None = None,
) -> tuple[
    SearchApplicationService,
    FakeProvider,
    FakeProvider,
    FakeCache,
    FakeRateLimiter,
    FakeConcurrencyLimiter,
    FakeUsage,
]:
    searxng = searxng or FakeProvider(SearchProviderId.SEARXNG)
    yandex = yandex or FakeProvider(SearchProviderId.YANDEX, billable=True)
    selected_cache = cache or FakeCache()
    rate = FakeRateLimiter()
    concurrency = FakeConcurrencyLimiter()
    usage = FakeUsage()
    service = SearchApplicationService(
        providers=SearchProviderRegistry((searxng, yandex), default_provider=default),
        regions=SearchRegionRegistry(()),
        cache=selected_cache,
        single_flight=FakeSingleFlight(),
        rate_limiter=rate,
        concurrency_limiter=concurrency,
        usage_uow_factory=usage,
        policy=policy or SearchServicePolicy(),
    )
    return service, searxng, yandex, selected_cache, rate, concurrency, usage


@pytest.mark.asyncio
async def test_default_and_explicit_provider_have_no_fallback() -> None:
    service, searxng, yandex, _, _, _, _ = build()
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(
                SearchQuery(query="default"),
                SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),
            )
        ),
    )
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data is not None
    assert [item.data.provider_id for item in result.data.items if item.data] == [
        SearchProviderId.SEARXNG,
        SearchProviderId.YANDEX,
    ]
    assert len(searxng.calls) == len(yandex.calls) == 1


@pytest.mark.asyncio
async def test_cache_hit_consumes_no_provider_rate_concurrency_or_usage() -> None:
    service, searxng, _, cache, rate, concurrency, usage = build()
    request = SearchBatchRequest(queries=(SearchQuery(query="same"),))
    first = await service.search(context(), request)
    second = await service.search(context(), request)
    assert first.data and second.data and second.data.items[0].data
    data = second.data.items[0].data
    assert data.cache.cached
    assert data.cache.retrieved_at == NOW
    assert data.usage.upstream_attempts == 0
    assert len(searxng.calls) == len(rate.calls) == len(concurrency.acquires) == 1
    assert usage.starts == []
    assert cache.gets == 2


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_success_and_adds_warning() -> None:
    cache = FakeCache()
    cache.write_ok = False
    service, *_ = build(cache=cache)
    result = await service.search(context(), SearchBatchRequest(queries=(SearchQuery(query="q"),)))
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data and result.data.items[0].warnings[0].code == "cache_write_failed"


@pytest.mark.asyncio
async def test_cache_scope_principal_shared_and_disabled_modes() -> None:
    principal_service, principal_provider, _, principal_cache, *_ = build()
    request = SearchBatchRequest(queries=(SearchQuery(query="scope"),))
    await principal_service.search(context(principal_id="one"), request)
    await principal_service.search(context(principal_id="two"), request)
    assert len(principal_provider.calls) == 2
    assert len(principal_cache.values) == 2

    shared_service, shared_provider, *_ = build(
        policy=SearchServicePolicy(cache_mode="shared_public")
    )
    await shared_service.search(context(principal_id="one"), request)
    shared_result = await shared_service.search(context(principal_id="two"), request)
    assert len(shared_provider.calls) == 1
    assert shared_result.data and shared_result.data.items[0].data
    assert shared_result.data.items[0].data.cache.cached

    disabled_service, disabled_provider, _, disabled_cache, *_ = build(
        policy=SearchServicePolicy(cache_mode="disabled")
    )
    await disabled_service.search(context(), request)
    await disabled_service.search(context(), request)
    assert len(disabled_provider.calls) == 2
    assert disabled_cache.gets == disabled_cache.puts == 0


@pytest.mark.asyncio
async def test_provider_configuration_revision_invalidates_cache_identity() -> None:
    cache = FakeCache()
    first_provider = FakeProvider(SearchProviderId.SEARXNG)
    first_service, *_ = build(searxng=first_provider, cache=cache)
    request = SearchBatchRequest(queries=(SearchQuery(query="revision"),))
    await first_service.search(context(), request)

    second_provider = FakeProvider(SearchProviderId.SEARXNG)
    second_provider.descriptor = second_provider.descriptor.model_copy(
        update={"configuration_revision": "revision-searxng-changed"}
    )
    second_service, *_ = build(searxng=second_provider, cache=cache)
    await second_service.search(context(), request)
    assert len(first_provider.calls) == len(second_provider.calls) == 1
    assert len(cache.values) == 2


@pytest.mark.asyncio
async def test_partial_batch_preserves_input_order_and_empty_result_is_success() -> None:
    failing = FakeProvider(SearchProviderId.YANDEX, billable=True)
    failing.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.UPSTREAM,
                code="provider_failure",
                message="failure",
            ),
            stage=ExecutionStage.TERMINAL_KNOWN,
        )
    )
    service, *_ = build(yandex=failing)
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(
                SearchQuery(query="ok"),
                SearchQuery(query="bad", provider=SearchProviderSelection.YANDEX),
            )
        ),
    )
    assert result.outcome is OperationOutcome.PARTIAL_SUCCESS
    assert result.data and [item.index for item in result.data.items] == [0, 1]
    assert [item.outcome for item in result.data.items] == [
        LeafOutcome.SUCCEEDED,
        LeafOutcome.FAILED,
    ]


@pytest.mark.asyncio
async def test_billable_retry_only_happens_for_proven_pre_dispatch_failure() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.UPSTREAM,
                code="connect_failed",
                message="connect failed",
                retryable=True,
            ),
            stage=ExecutionStage.BEFORE_DISPATCH,
        )
    )
    service, _, _, _, rate, concurrency, usage = build(
        yandex=yandex, policy=SearchServicePolicy(yandex_max_attempts=2)
    )
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="q", provider=SearchProviderSelection.YANDEX),)
        ),
    )
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert len(yandex.calls) == len(rate.calls) == len(concurrency.acquires) == 2
    assert [attempt for _, attempt in usage.starts] == [1, 2]
    assert usage.commits == 6


@pytest.mark.asyncio
async def test_billable_provider_fails_closed_before_network_when_usage_db_is_unavailable() -> None:
    service, _, yandex, *_ = build()
    service._usage = UnavailableUsage()
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )
    assert result.outcome is OperationOutcome.FAILED
    assert result.data and result.data.items[0].error
    assert result.data.items[0].error.code == "usage_accounting_unavailable"
    assert yandex.calls == []


@pytest.mark.asyncio
async def test_billable_provider_fails_closed_when_pre_dispatch_commit_fails() -> None:
    service, _, yandex, *_ = build()
    service._usage = CommitUnavailableUsage()
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )
    assert result.outcome is OperationOutcome.FAILED
    assert yandex.calls == []


@pytest.mark.asyncio
async def test_free_provider_does_not_require_usage_database() -> None:
    service, searxng, *_ = build()
    service._usage = None
    result = await service.search(
        context(), SearchBatchRequest(queries=(SearchQuery(query="free"),))
    )
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert len(searxng.calls) == 1


@pytest.mark.asyncio
async def test_possible_billable_dispatch_never_retries_or_falls_back() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.UNKNOWN_OUTCOME,
                code="response_lost",
                message="response lost",
                retryable=True,
            ),
            stage=ExecutionStage.RESPONSE_LOST,
        )
    )
    service, searxng, _, _, rate, _, usage = build(
        yandex=yandex, policy=SearchServicePolicy(yandex_max_attempts=2)
    )
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="q", provider=SearchProviderSelection.YANDEX),)
        ),
    )
    assert result.outcome is OperationOutcome.UNKNOWN
    assert len(yandex.calls) == len(rate.calls) == len(usage.starts) == 1
    assert searxng.calls == []


@pytest.mark.asyncio
async def test_cancellation_during_provider_call_releases_concurrency() -> None:
    searxng = FakeProvider(SearchProviderId.SEARXNG)
    searxng.wait_event = asyncio.Event()
    service, _, _, _, _, concurrency, _ = build(searxng=searxng)
    ctx = context()
    task = asyncio.create_task(
        service.search(ctx, SearchBatchRequest(queries=(SearchQuery(query="wait"),)))
    )
    await searxng.called_event.wait()
    assert isinstance(ctx.cancellation, CancellationToken)
    ctx.cancellation.request()
    result = await task
    assert result.outcome is OperationOutcome.CANCELLED
    assert concurrency.releases == 1


@pytest.mark.asyncio
async def test_expired_deadline_fails_without_provider_call() -> None:
    service, searxng, *_ = build()
    ctx = context()
    assert isinstance(ctx.clock, FakeClock)
    ctx.clock.advance(30)
    result = await service.search(ctx, SearchBatchRequest(queries=(SearchQuery(query="late"),)))
    assert result.outcome is OperationOutcome.FAILED
    assert searxng.calls == []
