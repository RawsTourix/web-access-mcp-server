"""S4 SearchApplicationService orchestration gates with deterministic fakes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
from web_access.application.common.results import (
    ExecutionStage,
    LeafOutcome,
    OperationOutcome,
    automatic_retry_allowed,
)
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
    AttemptStage,
    CacheLookup,
    CacheLookupState,
    ConcurrencyLease,
    ProviderAttemptError,
    RateAdmission,
    RateAdmissionStatus,
    SearchSingleFlight,
    SearchTelemetry,
    SearchUsageUnavailable,
    SearchUsageUnitOfWork,
    SingleFlightLease,
)
from web_access.application.search.registry import SearchProviderRegistry, SearchRegionRegistry
from web_access.application.search.service import SearchApplicationService, SearchServicePolicy
from web_access.core.time import Deadline, FakeClock, SystemClock
from web_access.domain.search import SearchProviderId, SearchProviderSelection, SearchResultItem
from web_access.infrastructure.observability import SearchTelemetryAdapter, create_metrics
from web_access.transport.mcp.retry import trusted_retry_descriptor

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
                max_query_length=400 if provider_id is SearchProviderId.YANDEX else 4096,
                max_query_words=40 if provider_id is SearchProviderId.YANDEX else None,
                max_result_window=250 if provider_id is SearchProviderId.YANDEX else None,
                billable=billable,
            ),
        )
        self.calls: list[ProviderSearchRequest] = []
        self.failures: list[ProviderAttemptError] = []
        self.wait_event: asyncio.Event | None = None
        self.called_event = asyncio.Event()
        self.before_search: Callable[[], None] | None = None
        self.results: tuple[SearchResultItem, ...] | None = None

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = context
        if self.before_search is not None:
            self.before_search()
        self.calls.append(request)
        self.called_event.set()
        if self.wait_event is not None:
            await self.wait_event.wait()
        if self.failures:
            raise self.failures.pop(0)
        return ProviderSearchResult(
            provider_id=self.descriptor.provider_id,
            results=(
                self.results
                if self.results is not None
                else (SearchResultItem(rank=1, title=request.query, url="https://example.test"),)
            ),
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


class RaisingCache(FakeCache):
    async def put(self, identity: str, value: SearchQueryData, ttl_seconds: int) -> bool:
        _ = identity, value, ttl_seconds
        self.puts += 1
        raise RuntimeError("redis unavailable")


class BlockingCache(FakeCache):
    def __init__(self, *, cancellation: CancellationToken | None = None) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self._cancellation = cancellation

    async def put(self, identity: str, value: SearchQueryData, ttl_seconds: int) -> bool:
        _ = identity, value, ttl_seconds
        self.puts += 1
        self.started.set()
        if self._cancellation is not None:
            self._cancellation.request()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return True


class FakeSingleFlight:
    def __init__(self) -> None:
        self.releases = 0

    async def acquire(self, identity: str, *, wait_seconds: float | None) -> SingleFlightLease:
        _ = wait_seconds
        return SingleFlightLease(identity=identity, holder=True, token="holder")

    async def release(self, lease: SingleFlightLease) -> None:
        _ = lease
        self.releases += 1


class CoordinatedSingleFlight:
    """Deterministically holds waiters behind one active cache identity."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active: dict[str, asyncio.Event] = {}
        self.waiter_joined = asyncio.Event()

    async def acquire(self, identity: str, *, wait_seconds: float | None) -> SingleFlightLease:
        _ = wait_seconds
        async with self._lock:
            event = self._active.get(identity)
            if event is None:
                self._active[identity] = asyncio.Event()
                return SingleFlightLease(identity=identity, holder=True, token="holder")
            self.waiter_joined.set()
        await event.wait()
        return SingleFlightLease(identity=identity, holder=False)

    async def release(self, lease: SingleFlightLease) -> None:
        async with self._lock:
            event = self._active.pop(lease.identity)
            event.set()


class FakeRateLimiter:
    def __init__(self) -> None:
        self.calls: list[SearchProviderId] = []
        self.allowed = True

    async def admit(
        self, *, principal_id: str, provider_id: SearchProviderId, wait_seconds: float | None
    ) -> RateAdmission:
        _ = principal_id, wait_seconds
        self.calls.append(provider_id)
        return RateAdmission(
            RateAdmissionStatus.ALLOWED if self.allowed else RateAdmissionStatus.RATE_LIMITED,
            None if self.allowed else 1,
        )


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
        self.rows: dict[tuple[str, int, int], dict[str, object]] = {}

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
        item_index = values["query_item_index"]
        assert isinstance(item_index, int)
        self.rows[(str(values["operation_id"]), item_index, attempt_number)] = {
            "stage": AttemptStage.PRE_DISPATCH,
            "outcome_code": None,
            "retry_reason": None,
        }

    async def mark_stage(self, **values: object) -> None:
        stage = values["stage"]
        item_index = values["query_item_index"]
        attempt_number = values["attempt_number"]
        assert isinstance(stage, AttemptStage)
        assert isinstance(item_index, int)
        assert isinstance(attempt_number, int)
        self.stages.append(stage.value)
        self.rows[(str(values["operation_id"]), item_index, attempt_number)] = {
            "stage": stage,
            "outcome_code": values.get("outcome_code"),
            "retry_reason": values.get("retry_reason"),
        }


class UnavailableUsage(FakeUsage):
    async def start_attempt(self, **values: object) -> None:
        _ = values
        raise SearchUsageUnavailable("database unavailable")


class CommitUnavailableUsage(FakeUsage):
    async def commit(self) -> None:
        raise SearchUsageUnavailable("commit unavailable")


class FailAtCommitUsage(FakeUsage):
    def __init__(self, fail_at: int) -> None:
        super().__init__()
        self.fail_at = fail_at
        self.committed_rows: dict[tuple[str, int, int], dict[str, object]] = {}

    async def commit(self) -> None:
        self.commits += 1
        if self.commits == self.fail_at:
            raise SearchUsageUnavailable("commit unavailable")
        self.committed_rows = {key: dict(value) for key, value in self.rows.items()}


class ReleaseLostSingleFlight(FakeSingleFlight):
    def __init__(self, cache: FakeCache) -> None:
        super().__init__()
        self._cache = cache
        self.cache_was_filled = False

    async def release(self, lease: SingleFlightLease) -> None:
        _ = lease
        self.releases += 1
        self.cache_was_filled = bool(self._cache.values)


def context(
    *,
    scopes: frozenset[str] = frozenset({"search:read"}),
    principal_id: str = "principal",
    operation_id: str = "op_test",
) -> ExecutionContext:
    clock = FakeClock(NOW)
    return ExecutionContext(
        operation_id=operation_id,
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
    single_flight: SearchSingleFlight | None = None,
    policy: SearchServicePolicy | None = None,
    telemetry: SearchTelemetry | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    random_source: Callable[[], float] = lambda: 0.5,
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
        single_flight=single_flight or FakeSingleFlight(),
        rate_limiter=rate,
        concurrency_limiter=concurrency,
        usage_uow_factory=usage,
        telemetry=telemetry,
        policy=policy or SearchServicePolicy(),
        sleeper=sleeper,
        random_source=random_source,
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
@pytest.mark.parametrize(
    "query",
    [
        SearchQuery(
            query="window",
            provider=SearchProviderSelection.YANDEX,
            page=6,
            limit=50,
        ),
        SearchQuery(
            query=" ".join(f"word{index}" for index in range(41)),
            provider=SearchProviderSelection.YANDEX,
        ),
        SearchQuery(query="x" * 401, provider=SearchProviderSelection.YANDEX),
    ],
)
async def test_known_yandex_limits_reject_before_all_admission_and_accounting(
    query: SearchQuery,
) -> None:
    service, _, yandex, _, rate, concurrency, usage = build()

    result = await service.search(context(), SearchBatchRequest(queries=(query,)))

    assert result.outcome is OperationOutcome.REJECTED
    assert yandex.calls == []
    assert rate.calls == []
    assert concurrency.acquires == []
    assert usage.starts == []
    assert result.data and result.data.items[0].error
    assert result.data.items[0].error.code == "unsupported_option"


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
    assert cache.gets == 3


@pytest.mark.asyncio
async def test_cache_write_failure_keeps_success_and_adds_warning() -> None:
    cache = FakeCache()
    cache.write_ok = False
    service, *_ = build(cache=cache)
    result = await service.search(context(), SearchBatchRequest(queries=(SearchQuery(query="q"),)))
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data and result.data.items[0].warnings[0].code == "cache_write_failed"


@pytest.mark.asyncio
async def test_cache_exception_after_provider_success_is_best_effort() -> None:
    cache = RaisingCache()
    service, provider, _, _, _, _, _ = build(cache=cache)
    result = await service.search(context(), SearchBatchRequest(queries=(SearchQuery(query="q"),)))

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert len(provider.calls) == 1
    assert result.data and result.data.items[0].warnings[0].code == "cache_write_failed"


@pytest.mark.asyncio
async def test_cache_deadline_after_paid_provider_success_preserves_success() -> None:
    cache = BlockingCache()
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    service, _, _, _, rate, concurrency, usage = build(yandex=yandex, cache=cache)
    clock = SystemClock()
    ctx = ExecutionContext(
        operation_id="op_cache_deadline",
        principal=PrincipalContext("principal", frozenset({"search:read"})),
        clock=clock,
        cancellation=CancellationToken(),
        deadline=Deadline.after(clock, 0.02),
    )

    result = await service.search(
        ctx,
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert len(yandex.calls) == len(rate.calls) == len(concurrency.acquires) == 1
    assert usage.rows[("op_cache_deadline", 0, 1)]["stage"] is AttemptStage.COMPLETED
    assert cache.cancelled.is_set()
    assert result.data and result.data.items[0].warnings[0].code == "cache_write_failed"


@pytest.mark.asyncio
async def test_cooperative_cancellation_after_paid_success_only_skips_cache() -> None:
    cancellation = CancellationToken()
    cache = BlockingCache(cancellation=cancellation)
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    service, _, _, _, rate, concurrency, usage = build(yandex=yandex, cache=cache)
    ctx = context(operation_id="op_cache_cancel")
    ctx = ExecutionContext(
        operation_id=ctx.operation_id,
        principal=ctx.principal,
        clock=ctx.clock,
        cancellation=cancellation,
        deadline=ctx.deadline,
    )

    result = await service.search(
        ctx,
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert len(yandex.calls) == len(rate.calls) == len(concurrency.acquires) == 1
    assert usage.rows[("op_cache_cancel", 0, 1)]["stage"] is AttemptStage.COMPLETED
    assert cache.cancelled.is_set()
    assert result.data and result.data.items[0].warnings[0].code == "cache_write_failed"


@pytest.mark.asyncio
async def test_cache_fill_survives_single_flight_release_loss() -> None:
    cache = FakeCache()
    flight = ReleaseLostSingleFlight(cache)
    service, searxng, _, _, rate, _, _ = build(cache=cache, single_flight=flight)
    request = SearchBatchRequest(queries=(SearchQuery(query="release-loss"),))

    first = await service.search(context(operation_id="op_first"), request)
    second = await service.search(context(operation_id="op_second"), request)

    assert first.outcome is second.outcome is OperationOutcome.SUCCEEDED
    assert flight.cache_was_filled is True
    assert len(searxng.calls) == len(rate.calls) == 1
    assert second.data and second.data.items[0].data
    assert second.data.items[0].data.cache.cached is True


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
async def test_empty_paid_result_is_success_without_fallback() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.results = ()
    service, searxng, *_ = build(yandex=yandex)

    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="empty", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data and result.data.items[0].data
    assert result.data.items[0].data.results == ()
    assert len(yandex.calls) == 1
    assert searxng.calls == []


@pytest.mark.asyncio
async def test_timeout_item_does_not_erase_sibling_or_trigger_fallback() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.TIMEOUT,
                code="provider_timeout",
                message="provider timed out",
                retryable=True,
            ),
            stage=ExecutionStage.RESPONSE_LOST,
        )
    )
    service, searxng, *_ = build(yandex=yandex, policy=SearchServicePolicy(yandex_max_attempts=2))

    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(
                SearchQuery(query="sibling"),
                SearchQuery(query="timeout", provider=SearchProviderSelection.YANDEX),
            )
        ),
    )

    assert result.outcome is OperationOutcome.PARTIAL_SUCCESS
    assert result.data
    assert [item.outcome for item in result.data.items] == [
        LeafOutcome.SUCCEEDED,
        LeafOutcome.UNKNOWN,
    ]
    assert len(searxng.calls) == len(yandex.calls) == 1


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
    metrics = create_metrics()
    service, _, _, _, rate, concurrency, usage = build(
        yandex=yandex,
        policy=SearchServicePolicy(yandex_max_attempts=2),
        telemetry=SearchTelemetryAdapter(metrics),
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
    assert usage.rows[("op_test", 0, 1)] == {
        "stage": AttemptStage.DISPATCH_POSSIBLE,
        "outcome_code": "connect_failed",
        "retry_reason": "connect_failed",
    }
    assert usage.rows[("op_test", 0, 2)] == {
        "stage": AttemptStage.COMPLETED,
        "outcome_code": "succeeded",
        "retry_reason": None,
    }
    assert 'reason="pre_dispatch_failure"' in metrics.render().decode()


@pytest.mark.asyncio
async def test_billable_network_code_runs_only_after_durable_dispatch_evidence() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    service, _, _, _, _, _, usage = build(yandex=yandex)

    def verify_preconditions() -> None:
        assert usage.commits == 2
        assert usage.stages == [AttemptStage.DISPATCH_POSSIBLE.value]

    yandex.before_search = verify_preconditions
    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert usage.commits == 3
    assert usage.stages == [AttemptStage.DISPATCH_POSSIBLE.value, AttemptStage.COMPLETED.value]


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
async def test_dispatch_evidence_commit_failure_keeps_durable_pre_dispatch_only() -> None:
    service, _, yandex, *_ = build()
    usage = FailAtCommitUsage(fail_at=2)
    service._usage = usage

    result = await service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    assert result.outcome is OperationOutcome.FAILED
    assert yandex.calls == []
    assert usage.commits == 2
    assert usage.committed_rows == {
        ("op_test", 0, 1): {
            "stage": AttemptStage.PRE_DISPATCH,
            "outcome_code": None,
            "retry_reason": None,
        }
    }


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
async def test_search_service_emits_cache_admission_retry_and_billable_metrics() -> None:
    metrics = create_metrics()
    telemetry = SearchTelemetryAdapter(metrics)
    searxng = FakeProvider(SearchProviderId.SEARXNG)
    searxng.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.TIMEOUT,
                code="temporary_timeout",
                message="temporary",
                retryable=True,
            ),
            stage=ExecutionStage.RESPONSE_LOST,
        )
    )
    service, *_ = build(searxng=searxng, telemetry=telemetry)
    request = SearchBatchRequest(queries=(SearchQuery(query="metrics"),))
    await service.search(context(), request)
    await service.search(context(), request)

    paid_service, *_ = build(telemetry=telemetry)
    await paid_service.search(
        context(),
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    rejected_service, _, _, _, rate, _, _ = build(telemetry=telemetry)
    rate.allowed = False
    await rejected_service.search(
        context(), SearchBatchRequest(queries=(SearchQuery(query="rejected"),))
    )
    capacity_service, _, _, _, _, concurrency, _ = build(telemetry=telemetry)
    concurrency.available = False
    await capacity_service.search(
        context(), SearchBatchRequest(queries=(SearchQuery(query="capacity"),))
    )
    rendered = metrics.render().decode()
    for expected in (
        'state="miss"',
        'state="hit"',
        'reason="timeout"',
        'kind="rate"',
        'kind="concurrency"',
        'stage="pre_dispatch"',
        'stage="dispatch_possible"',
        'stage="completed"',
    ):
        assert expected in rendered


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
    assert usage.rows == {
        ("op_test", 0, 1): {
            "stage": AttemptStage.DISPATCH_POSSIBLE,
            "outcome_code": "response_lost",
            "retry_reason": None,
        }
    }


@pytest.mark.asyncio
async def test_billable_cache_hit_has_zero_cost_for_second_operation() -> None:
    service, _, yandex, _, rate, concurrency, usage = build()
    request = SearchBatchRequest(
        queries=(SearchQuery(query="paid-cache", provider=SearchProviderSelection.YANDEX),)
    )
    first = await service.search(context(operation_id="op_first"), request)
    second = await service.search(context(operation_id="op_second"), request)

    assert first.outcome is second.outcome is OperationOutcome.SUCCEEDED
    assert len(yandex.calls) == len(rate.calls) == len(concurrency.acquires) == 1
    assert usage.starts == [("op_first", 1)]
    assert set(usage.rows) == {("op_first", 0, 1)}
    assert second.data and second.data.items[0].data
    assert second.data.items[0].data.cache.cached is True
    assert second.data.items[0].data.usage.upstream_attempts == 0
    assert second.data.items[0].data.usage.billable_attempts == 0
    assert second.data.items[0].data.usage.rate_units == 0


@pytest.mark.asyncio
async def test_explicit_second_operation_is_not_hidden_retry_or_fallback() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    for _ in range(2):
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
    request = SearchBatchRequest(
        queries=(SearchQuery(query="explicit", provider=SearchProviderSelection.YANDEX),)
    )

    first = await service.search(context(operation_id="op_first"), request)
    second = await service.search(context(operation_id="op_second"), request)

    assert first.outcome is second.outcome is OperationOutcome.UNKNOWN
    assert len(yandex.calls) == len(rate.calls) == 2
    assert searxng.calls == []
    assert usage.starts == [("op_first", 1), ("op_second", 1)]
    assert set(usage.rows) == {("op_first", 0, 1), ("op_second", 0, 1)}
    assert all(row["retry_reason"] is None for row in usage.rows.values())


def test_mcp_trusted_retry_descriptor_blocks_paid_response_loss_replay() -> None:
    descriptor = trusted_retry_descriptor("web_search")
    assert descriptor is not None
    assert automatic_retry_allowed(
        retry_class=descriptor.retry_class,
        stage=ExecutionStage.BEFORE_DISPATCH,
        effects=descriptor.effects,
        error_retryable=True,
    )
    assert not automatic_retry_allowed(
        retry_class=descriptor.retry_class,
        stage=ExecutionStage.RESPONSE_LOST,
        effects=descriptor.effects,
        error_retryable=True,
    )


@pytest.mark.asyncio
async def test_single_flight_response_loss_creates_one_tracked_billable_call() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.wait_event = asyncio.Event()
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
    single_flight = CoordinatedSingleFlight()
    service, searxng, _, _, rate, concurrency, usage = build(
        yandex=yandex,
        single_flight=single_flight,
        policy=SearchServicePolicy(yandex_max_attempts=2),
    )
    request = SearchBatchRequest(
        queries=(SearchQuery(query="concurrent-paid", provider=SearchProviderSelection.YANDEX),)
    )
    holder = asyncio.create_task(service.search(context(operation_id="op_holder"), request))
    await yandex.called_event.wait()
    waiter = asyncio.create_task(service.search(context(operation_id="op_waiter"), request))
    await single_flight.waiter_joined.wait()
    yandex.wait_event.set()
    results = await asyncio.gather(holder, waiter)

    assert {result.outcome for result in results} == {
        OperationOutcome.UNKNOWN,
        OperationOutcome.FAILED,
    }
    assert len(yandex.calls) == len(rate.calls) == len(concurrency.acquires) == 1
    assert searxng.calls == []
    assert usage.starts == [("op_holder", 1)]
    assert usage.rows == {
        ("op_holder", 0, 1): {
            "stage": AttemptStage.DISPATCH_POSSIBLE,
            "outcome_code": "response_lost",
            "retry_reason": None,
        }
    }


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


@pytest.mark.asyncio
async def test_missing_caller_deadline_is_bounded_by_service_policy() -> None:
    searxng = FakeProvider(SearchProviderId.SEARXNG)
    searxng.wait_event = asyncio.Event()
    service, *_ = build(
        searxng=searxng,
        policy=SearchServicePolicy(operation_timeout_seconds=0.02),
    )
    clock = SystemClock()
    unbounded_caller = ExecutionContext(
        operation_id="op_no_deadline",
        principal=PrincipalContext("principal", frozenset({"search:read"})),
        clock=clock,
        cancellation=CancellationToken(),
    )

    result = await service.search(
        unbounded_caller,
        SearchBatchRequest(queries=(SearchQuery(query="bounded"),)),
    )

    assert result.outcome is OperationOutcome.FAILED
    assert result.error is not None and result.error.category is ErrorCategory.TIMEOUT
    assert len(searxng.calls) == 1


@pytest.mark.asyncio
async def test_retry_backoff_jitter_and_retry_after_share_remaining_deadline() -> None:
    searxng = FakeProvider(SearchProviderId.SEARXNG)
    searxng.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.RATE_LIMITED,
                code="retry_later",
                message="retry",
                retryable=True,
                retry_after_seconds=2,
            ),
            stage=ExecutionStage.TERMINAL_KNOWN,
        )
    )
    sleeps: list[float] = []
    ctx = context()
    assert isinstance(ctx.clock, FakeClock)
    fake_clock = ctx.clock

    async def advance(delay: float) -> None:
        sleeps.append(delay)
        fake_clock.advance(delay)

    service, _, _, _, rate, concurrency, _ = build(
        searxng=searxng,
        policy=SearchServicePolicy(
            searxng_max_attempts=2,
            retry_backoff_seconds=1,
            retry_jitter_ratio=0.5,
        ),
        sleeper=advance,
        random_source=lambda: 1.0,
    )
    result = await service.search(ctx, SearchBatchRequest(queries=(SearchQuery(query="retry"),)))

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert sleeps == [2.0]
    assert len(searxng.calls) == len(rate.calls) == len(concurrency.acquires) == 2
    assert searxng.calls[1] is not searxng.calls[0]


@pytest.mark.asyncio
async def test_retry_does_not_start_when_retry_after_exceeds_remaining_budget() -> None:
    searxng = FakeProvider(SearchProviderId.SEARXNG)
    searxng.failures.append(
        ProviderAttemptError(
            OperationError(
                category=ErrorCategory.RATE_LIMITED,
                code="retry_later",
                message="retry",
                retryable=True,
                retry_after_seconds=2,
            ),
            stage=ExecutionStage.TERMINAL_KNOWN,
        )
    )
    service, *_ = build(
        searxng=searxng,
        policy=SearchServicePolicy(searxng_max_attempts=2),
    )
    ctx = context()
    assert isinstance(ctx.clock, FakeClock)
    ctx = ExecutionContext(
        operation_id=ctx.operation_id,
        principal=ctx.principal,
        clock=ctx.clock,
        cancellation=ctx.cancellation,
        deadline=Deadline.after(ctx.clock, 1),
    )

    result = await service.search(ctx, SearchBatchRequest(queries=(SearchQuery(query="no-retry"),)))

    assert result.outcome is OperationOutcome.FAILED
    assert result.error is not None and result.error.category is ErrorCategory.TIMEOUT
    assert len(searxng.calls) == 1


@pytest.mark.asyncio
async def test_billable_cooperative_cancellation_after_dispatch_is_unknown() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.wait_event = asyncio.Event()
    service, _, _, _, _, concurrency, usage = build(yandex=yandex)
    ctx = context()
    task = asyncio.create_task(
        service.search(
            ctx,
            SearchBatchRequest(
                queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
            ),
        )
    )
    await yandex.called_event.wait()
    assert isinstance(ctx.cancellation, CancellationToken)
    ctx.cancellation.request()
    result = await task

    assert result.outcome is OperationOutcome.UNKNOWN
    assert len(yandex.calls) == 1
    assert concurrency.releases == 1
    assert usage.rows[("op_test", 0, 1)] == {
        "stage": AttemptStage.DISPATCH_POSSIBLE,
        "outcome_code": "unknown",
        "retry_reason": None,
    }


@pytest.mark.asyncio
async def test_billable_deadline_after_dispatch_is_unknown_without_retry() -> None:
    yandex = FakeProvider(SearchProviderId.YANDEX, billable=True)
    yandex.wait_event = asyncio.Event()
    service, _, _, _, rate, concurrency, usage = build(
        yandex=yandex,
        policy=SearchServicePolicy(yandex_max_attempts=2, operation_timeout_seconds=0.02),
    )
    clock = SystemClock()
    ctx = ExecutionContext(
        operation_id="op_deadline_dispatch",
        principal=PrincipalContext("principal", frozenset({"search:read"})),
        clock=clock,
        cancellation=CancellationToken(),
    )
    result = await service.search(
        ctx,
        SearchBatchRequest(
            queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
        ),
    )

    assert result.outcome is OperationOutcome.UNKNOWN
    assert len(yandex.calls) == len(rate.calls) == 1
    assert concurrency.releases == 1
    assert usage.rows[("op_deadline_dispatch", 0, 1)]["outcome_code"] == "unknown"


@pytest.mark.asyncio
async def test_direct_task_cancel_finishes_billable_child_before_concurrency_release() -> None:
    child_finished = asyncio.Event()

    class CancelAwareProvider(FakeProvider):
        async def search(
            self, context: ExecutionContext, request: ProviderSearchRequest
        ) -> ProviderSearchResult:
            try:
                return await super().search(context, request)
            finally:
                child_finished.set()

    class OrderingConcurrency(FakeConcurrencyLimiter):
        async def release(self, lease: ConcurrencyLease) -> None:
            assert child_finished.is_set()
            await super().release(lease)

    yandex = CancelAwareProvider(SearchProviderId.YANDEX, billable=True)
    yandex.wait_event = asyncio.Event()
    service, *_ = build(yandex=yandex)
    ordering = OrderingConcurrency()
    service._concurrency = ordering
    task = asyncio.create_task(
        service.search(
            context(),
            SearchBatchRequest(
                queries=(SearchQuery(query="paid", provider=SearchProviderSelection.YANDEX),)
            ),
        )
    )
    await yandex.called_event.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert child_finished.is_set()
    assert len(yandex.calls) == 1
    assert ordering.releases == 1
