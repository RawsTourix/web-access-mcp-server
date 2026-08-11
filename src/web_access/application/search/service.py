"""Framework-independent Search batch orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from web_access.application.common.auth import require_scope
from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import ErrorCategory, OperationError
from web_access.application.common.hints import Warning
from web_access.application.common.results import (
    BatchItemResult,
    ExecutionStage,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
    aggregate_batch_outcome,
)
from web_access.application.search.models import (
    CacheMetadata,
    PaginationMetadata,
    ProviderSearchRequest,
    ProviderSearchResult,
    SearchBatchRequest,
    SearchBatchResult,
    SearchQuery,
    SearchQueryData,
    SearchUsageMetadata,
)
from web_access.application.search.ports import (
    AttemptStage,
    CacheLookupState,
    ProviderAttemptError,
    ProviderConcurrencyLimiter,
    ProviderRateLimiter,
    RateAdmissionStatus,
    SearchCache,
    SearchProvider,
    SearchSingleFlight,
    SearchTelemetry,
    SearchUsageUnavailable,
    SearchUsageUnitOfWorkFactory,
    SingleFlightLease,
)
from web_access.application.search.registry import (
    ProviderResolutionError,
    SearchProviderRegistry,
    SearchRegionRegistry,
)
from web_access.core.time import Deadline
from web_access.domain.search import SearchProviderId

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SearchServicePolicy:
    cache_mode: str = "principal"
    searxng_cache_ttl_seconds: int = 300
    yandex_cache_ttl_seconds: int = 300
    searxng_max_attempts: int = 2
    yandex_max_attempts: int = 1
    batch_concurrency: int = 8
    operation_timeout_seconds: float = 30.0
    retry_backoff_seconds: float = 0.05
    retry_jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.cache_mode not in {"principal", "shared_public", "disabled"}:
            raise ValueError("invalid Search cache mode")
        if not 1 <= self.batch_concurrency <= 32:
            raise ValueError("invalid Search batch concurrency")
        if self.operation_timeout_seconds <= 0:
            raise ValueError("invalid Search operation timeout")
        if self.retry_backoff_seconds < 0 or not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("invalid Search retry timing policy")
        for value in (
            self.searxng_cache_ttl_seconds,
            self.yandex_cache_ttl_seconds,
            self.searxng_max_attempts,
            self.yandex_max_attempts,
        ):
            if value < 1:
                raise ValueError("invalid Search service policy")

    def cache_ttl(self, provider_id: SearchProviderId) -> int:
        return (
            self.searxng_cache_ttl_seconds
            if provider_id is SearchProviderId.SEARXNG
            else self.yandex_cache_ttl_seconds
        )

    def max_attempts(self, provider_id: SearchProviderId) -> int:
        return (
            self.searxng_max_attempts
            if provider_id is SearchProviderId.SEARXNG
            else self.yandex_max_attempts
        )


class _CooperativeCancellation(Exception):
    pass


class _DeadlineExceeded(Exception):
    pass


class _NoopSearchTelemetry:
    def observe_cache(self, provider_id: SearchProviderId, state: CacheLookupState) -> None:
        _ = provider_id, state

    def observe_admission_rejection(self, provider_id: SearchProviderId, kind: str) -> None:
        _ = provider_id, kind

    def observe_internal_retry(self, provider_id: SearchProviderId, reason: str) -> None:
        _ = provider_id, reason

    def observe_billable_attempt(
        self, provider_id: SearchProviderId, stage: AttemptStage, outcome: str
    ) -> None:
        _ = provider_id, stage, outcome

    def observe_provider_readiness(self, provider_id: SearchProviderId, status: str) -> None:
        _ = provider_id, status


async def _bounded_await(context: ExecutionContext, awaitable: Awaitable[_T]) -> _T:
    task = asyncio.ensure_future(awaitable)
    remaining = context.remaining_seconds()
    if remaining is not None and remaining <= 0:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise _DeadlineExceeded
    if context.cancellation.requested:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise _CooperativeCancellation

    cancellation = asyncio.create_task(context.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (task, cancellation), timeout=remaining, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            return await task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if cancellation in done:
            raise _CooperativeCancellation
        raise _DeadlineExceeded
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    finally:
        cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)


class SearchApplicationService:
    def __init__(
        self,
        *,
        providers: SearchProviderRegistry,
        regions: SearchRegionRegistry,
        cache: SearchCache,
        single_flight: SearchSingleFlight,
        rate_limiter: ProviderRateLimiter,
        concurrency_limiter: ProviderConcurrencyLimiter,
        usage_uow_factory: SearchUsageUnitOfWorkFactory | None,
        telemetry: SearchTelemetry | None = None,
        policy: SearchServicePolicy | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._providers = providers
        self._regions = regions
        self._cache = cache
        self._single_flight = single_flight
        self._rate = rate_limiter
        self._concurrency = concurrency_limiter
        self._usage = usage_uow_factory
        self._telemetry = telemetry or _NoopSearchTelemetry()
        self._policy = policy or SearchServicePolicy()
        self._sleeper = sleeper
        self._random = random_source

    async def search(
        self, context: ExecutionContext, request: SearchBatchRequest
    ) -> OperationResult[SearchBatchResult]:
        require_scope(context.principal, "search:read")
        if context.deadline is None:
            context = replace(
                context,
                deadline=Deadline.after(context.clock, self._policy.operation_timeout_seconds),
            )
        semaphore = asyncio.Semaphore(self._policy.batch_concurrency)

        async def run(index: int, query: SearchQuery) -> BatchItemResult[SearchQueryData]:
            try:
                await _bounded_await(context, semaphore.acquire())
            except _CooperativeCancellation:
                return self._error_item(
                    index,
                    LeafOutcome.CANCELLED,
                    ErrorCategory.CANCELLED,
                    "search_cancelled",
                    "Поисковый запрос отменён до получения batch-слота.",
                )
            except _DeadlineExceeded:
                return self._error_item(
                    index,
                    LeafOutcome.FAILED,
                    ErrorCategory.TIMEOUT,
                    "search_deadline_exceeded",
                    "Истёк общий срок ожидания batch-слота.",
                )
            try:
                return await self._search_item(context, index, query)
            finally:
                semaphore.release()

        pending = (run(index, query) for index, query in enumerate(request.queries))
        items = tuple(await asyncio.gather(*pending))
        outcome = aggregate_batch_outcome([item.outcome for item in items])
        error = None
        if outcome not in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
            error = _aggregate_error(outcome, items)
        return OperationResult(
            operation_id=context.operation_id,
            outcome=outcome,
            data=SearchBatchResult(items=items),
            error=error,
        )

    async def _search_item(
        self, context: ExecutionContext, index: int, query: SearchQuery
    ) -> BatchItemResult[SearchQueryData]:
        lease: SingleFlightLease | None = None
        try:
            provider = self._providers.resolve(query.provider)
            self._providers.validate_capabilities(provider, query)
            provider_id = provider.descriptor.provider_id
            provider_region = None
            if query.region is not None:
                provider_region = self._regions.provider_region(str(query.region), provider_id)
            identity = self._cache_identity(
                context=context,
                query=query,
                provider_id=provider_id,
                provider_revision=provider.descriptor.configuration_revision,
            )

            if self._policy.cache_mode != "disabled":
                cached = await _bounded_await(context, self._cache.get(identity))
                self._telemetry.observe_cache(provider_id, cached.state)
                if cached.state is CacheLookupState.HIT and cached.value is not None:
                    return self._cache_hit(index, cached.value)
                lease = await _bounded_await(
                    context,
                    self._single_flight.acquire(identity, wait_seconds=context.remaining_seconds()),
                )
                # A waiter may become holder immediately after the previous
                # holder filled the cache and released its Redis lease.
                cached = await _bounded_await(context, self._cache.get(identity))
                self._telemetry.observe_cache(provider_id, cached.state)
                if cached.state is CacheLookupState.HIT and cached.value is not None:
                    return self._cache_hit(index, cached.value)
                if not lease.holder:
                    raise ProviderAttemptError(
                        OperationError(
                            category=ErrorCategory.CAPACITY,
                            code="single_flight_wait_exhausted",
                            message="Ожидание совпадающего поискового запроса исчерпано.",
                            retryable=True,
                        ),
                        stage=ExecutionStage.BEFORE_DISPATCH,
                    )

            result, attempts = await self._execute_attempts(
                context=context,
                index=index,
                query=query,
                provider_region=provider_region,
                provider=provider,
            )
            data = SearchQueryData(
                query=query.query,
                provider_id=provider_id,
                page=query.page,
                requested_limit=query.limit,
                results=result.results[: query.limit],
                cache=CacheMetadata(cached=False, retrieved_at=result.retrieved_at),
                pagination=PaginationMetadata(
                    page=query.page, next_page_available=result.next_page_available
                ),
                usage=SearchUsageMetadata(
                    upstream_attempts=attempts,
                    rate_units=attempts,
                    billable_attempts=attempts if provider.descriptor.billable else 0,
                    internal_retries=max(0, attempts - 1),
                ),
            )
            warnings = list(result.warnings)
            if self._policy.cache_mode != "disabled":
                stored = await self._best_effort_cache_put(
                    context=context,
                    provider_id=provider_id,
                    identity=identity,
                    data=data,
                )
                if not stored:
                    warnings.append(
                        Warning(
                            code="cache_write_failed",
                            message="Результат поиска получен, но сохранить его в кэше не удалось.",
                        )
                    )
            return BatchItemResult(
                index=index,
                outcome=LeafOutcome.SUCCEEDED,
                data=data,
                warnings=tuple(warnings),
            )
        except ProviderResolutionError as error:
            return self._error_item(
                index,
                LeafOutcome.REJECTED,
                ErrorCategory.UNSUPPORTED,
                error.code,
                str(error),
            )
        except ProviderAttemptError as error:
            outcome = (
                LeafOutcome.UNKNOWN
                if error.stage
                in {ExecutionStage.SIDE_EFFECT_POSSIBLE, ExecutionStage.RESPONSE_LOST}
                else LeafOutcome.FAILED
            )
            return BatchItemResult(index=index, outcome=outcome, error=error.error)
        except _CooperativeCancellation:
            return self._error_item(
                index,
                LeafOutcome.CANCELLED,
                ErrorCategory.CANCELLED,
                "search_cancelled",
                "Поисковый запрос отменён.",
            )
        except _DeadlineExceeded:
            return self._error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.TIMEOUT,
                "search_deadline_exceeded",
                "Истёк общий срок выполнения поискового запроса.",
            )
        finally:
            if lease is not None and lease.holder:
                await self._single_flight.release(lease)

    async def _best_effort_cache_put(
        self,
        *,
        context: ExecutionContext,
        provider_id: SearchProviderId,
        identity: str,
        data: SearchQueryData,
    ) -> bool:
        """Never replace a terminal provider success with optional cache failure."""

        try:
            stored = await _bounded_await(
                context,
                self._cache.put(identity, data, self._policy.cache_ttl(provider_id)),
            )
        except Exception:
            stored = False
        if not stored:
            self._telemetry.observe_cache(provider_id, CacheLookupState.UNAVAILABLE)
        return stored

    async def _execute_attempts(
        self,
        *,
        context: ExecutionContext,
        index: int,
        query: SearchQuery,
        provider_region: str | None,
        provider: SearchProvider,
    ) -> tuple[ProviderSearchResult, int]:
        descriptor = provider.descriptor
        provider_id = descriptor.provider_id
        max_attempts = self._policy.max_attempts(provider_id)
        for attempt in range(1, max_attempts + 1):
            admission = await _bounded_await(
                context,
                self._rate.admit(
                    principal_id=context.principal.principal_id,
                    provider_id=provider_id,
                    wait_seconds=context.remaining_seconds(),
                ),
            )
            if admission.status is RateAdmissionStatus.UNAVAILABLE:
                self._telemetry.observe_admission_rejection(provider_id, "admission_unavailable")
                raise ProviderAttemptError(
                    OperationError(
                        category=ErrorCategory.INFRASTRUCTURE,
                        code="search_admission_unavailable",
                        message="Инфраструктура допуска поисковых запросов недоступна.",
                        retryable=True,
                    ),
                    stage=ExecutionStage.BEFORE_DISPATCH,
                )
            if admission.status is RateAdmissionStatus.RATE_LIMITED:
                self._telemetry.observe_admission_rejection(provider_id, "rate")
                raise ProviderAttemptError(
                    OperationError(
                        category=ErrorCategory.RATE_LIMITED,
                        code="provider_rate_limited",
                        message="Лимит частоты запросов к поисковому provider исчерпан.",
                        retryable=True,
                        retry_after_seconds=(
                            None
                            if admission.retry_after_seconds is None
                            else max(0, round(admission.retry_after_seconds))
                        ),
                    ),
                    stage=ExecutionStage.BEFORE_DISPATCH,
                )
            concurrency = await _bounded_await(
                context,
                self._concurrency.acquire(provider_id, wait_seconds=context.remaining_seconds()),
            )
            if concurrency is None:
                self._telemetry.observe_admission_rejection(provider_id, "concurrency")
                raise ProviderAttemptError(
                    OperationError(
                        category=ErrorCategory.CAPACITY,
                        code="provider_capacity_unavailable",
                        message="Свободная ёмкость поискового provider недоступна.",
                        retryable=True,
                    ),
                    stage=ExecutionStage.BEFORE_DISPATCH,
                )
            try:
                if descriptor.billable:
                    if self._usage is None:
                        raise ProviderAttemptError(
                            OperationError(
                                category=ErrorCategory.INFRASTRUCTURE,
                                code="usage_accounting_unavailable",
                                message="Учёт платного поискового запроса недоступен.",
                            ),
                            stage=ExecutionStage.BEFORE_DISPATCH,
                        )
                    await self._record_attempt_start(
                        context=context,
                        provider_id=provider_id,
                        index=index,
                        attempt=attempt,
                    )
                    await self._record_attempt_stage(
                        context=context,
                        provider_id=provider_id,
                        index=index,
                        attempt=attempt,
                        stage=AttemptStage.DISPATCH_POSSIBLE,
                        outcome_code="unknown",
                    )
                request = ProviderSearchRequest(
                    query=query.query,
                    provider_id=provider_id,
                    page=query.page,
                    limit=query.limit,
                    language=query.language,
                    region=query.region,
                    provider_region=provider_region,
                    safe_search=query.safe_search,
                    time_range=query.time_range,
                )
                try:
                    result = await _bounded_await(context, provider.search(context, request))
                except (_CooperativeCancellation, _DeadlineExceeded) as termination:
                    if descriptor.billable:
                        code = (
                            "search_cancelled_after_dispatch"
                            if isinstance(termination, _CooperativeCancellation)
                            else "search_deadline_after_dispatch"
                        )
                        raise ProviderAttemptError(
                            OperationError(
                                category=ErrorCategory.UNKNOWN_OUTCOME,
                                code=code,
                                message=("Платный запрос мог быть отправлен; его итог неизвестен."),
                                retryable=False,
                            ),
                            stage=ExecutionStage.SIDE_EFFECT_POSSIBLE,
                        ) from termination
                    raise
                except ProviderAttemptError as error:
                    will_retry = attempt < max_attempts and self._retry_allowed(
                        billable=descriptor.billable, error=error
                    )
                    if descriptor.billable and self._usage is not None:
                        await self._record_attempt_stage(
                            context=context,
                            provider_id=provider_id,
                            index=index,
                            attempt=attempt,
                            stage=(
                                AttemptStage.RESPONSE_RECEIVED
                                if error.stage is ExecutionStage.TERMINAL_KNOWN
                                else AttemptStage.DISPATCH_POSSIBLE
                            ),
                            outcome_code=error.error.code,
                            retry_reason=error.error.code if will_retry else None,
                            provider_request_id=error.provider_request_id,
                            accounting_failure_stage=ExecutionStage.RESPONSE_LOST,
                        )
                    if will_retry:
                        self._telemetry.observe_internal_retry(provider_id, _retry_reason(error))
                        await self._wait_before_retry(context, attempt, error)
                        continue
                    raise
                if descriptor.billable and self._usage is not None:
                    await self._record_attempt_stage(
                        context=context,
                        provider_id=provider_id,
                        index=index,
                        attempt=attempt,
                        stage=AttemptStage.COMPLETED,
                        outcome_code="succeeded",
                        provider_request_id=result.provider_request_id,
                        accounting_failure_stage=ExecutionStage.RESPONSE_LOST,
                    )
                return result, attempt
            finally:
                await self._concurrency.release(concurrency)
        raise RuntimeError("unreachable Search attempt state")

    async def _record_attempt_start(
        self,
        *,
        context: ExecutionContext,
        provider_id: SearchProviderId,
        index: int,
        attempt: int,
    ) -> None:
        factory = self._usage
        if factory is None:
            raise RuntimeError("Search usage factory is not configured")
        try:
            async with factory() as uow:
                await _bounded_await(
                    context,
                    uow.usage.start_attempt(
                        operation_id=context.operation_id,
                        principal_id=context.principal.principal_id,
                        provider_id=provider_id,
                        query_item_index=index,
                        attempt_number=attempt,
                    ),
                )
                await _bounded_await(context, uow.commit())
            self._telemetry.observe_billable_attempt(
                provider_id, AttemptStage.PRE_DISPATCH, "started"
            )
        except SearchUsageUnavailable as exc:
            raise self._usage_error() from exc

    async def _record_attempt_stage(
        self,
        *,
        context: ExecutionContext,
        provider_id: SearchProviderId,
        index: int,
        attempt: int,
        stage: AttemptStage,
        outcome_code: str | None = None,
        retry_reason: str | None = None,
        provider_request_id: str | None = None,
        accounting_failure_stage: ExecutionStage = ExecutionStage.BEFORE_DISPATCH,
    ) -> None:
        factory = self._usage
        if factory is None:
            raise RuntimeError("Search usage factory is not configured")
        try:
            async with factory() as uow:
                await _bounded_await(
                    context,
                    uow.usage.mark_stage(
                        operation_id=context.operation_id,
                        provider_id=provider_id,
                        query_item_index=index,
                        attempt_number=attempt,
                        stage=stage,
                        outcome_code=outcome_code,
                        retry_reason=retry_reason,
                        provider_request_id=provider_request_id,
                    ),
                )
                await _bounded_await(context, uow.commit())
            self._telemetry.observe_billable_attempt(
                provider_id,
                stage,
                _billable_outcome(
                    stage=stage, outcome_code=outcome_code, retry_reason=retry_reason
                ),
            )
        except SearchUsageUnavailable as exc:
            raise self._usage_error(accounting_failure_stage) from exc

    @staticmethod
    def _usage_error(
        stage: ExecutionStage = ExecutionStage.BEFORE_DISPATCH,
    ) -> ProviderAttemptError:
        return ProviderAttemptError(
            OperationError(
                category=ErrorCategory.INFRASTRUCTURE,
                code="usage_accounting_unavailable",
                message="Учёт платного поискового запроса недоступен.",
                retryable=False,
            ),
            stage=stage,
        )

    @staticmethod
    def _retry_allowed(*, billable: bool, error: ProviderAttemptError) -> bool:
        if not error.error.retryable:
            return False
        if billable:
            return error.stage is ExecutionStage.BEFORE_DISPATCH
        return True

    async def _wait_before_retry(
        self,
        context: ExecutionContext,
        attempt: int,
        error: ProviderAttemptError,
    ) -> None:
        configured = self._policy.retry_backoff_seconds * (2 ** (attempt - 1))
        jitter = configured * self._policy.retry_jitter_ratio * (2 * self._random() - 1)
        delay = max(0.0, configured + jitter)
        if error.error.retry_after_seconds is not None:
            delay = max(delay, float(error.error.retry_after_seconds))
        remaining = context.remaining_seconds()
        if remaining is not None and (remaining <= 0 or delay >= remaining):
            raise _DeadlineExceeded
        if delay:
            await _bounded_await(context, self._sleeper(delay))

    def _cache_identity(
        self,
        *,
        context: ExecutionContext,
        query: SearchQuery,
        provider_id: SearchProviderId,
        provider_revision: str,
    ) -> str:
        scope = None
        if self._policy.cache_mode == "principal":
            scope = context.principal.principal_id
        payload = {
            "schema": 1,
            "provider_id": provider_id.value,
            "provider_revision": provider_revision,
            "region_revision": self._regions.revision,
            "query": query.query,
            "page": query.page,
            "limit": query.limit,
            "language": None if query.language is None else str(query.language),
            "region": None if query.region is None else str(query.region),
            "safe_search": None if query.safe_search is None else query.safe_search.value,
            "time_range": None if query.time_range is None else query.time_range.value,
            "cache_mode": self._policy.cache_mode,
            "scope": scope,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"search:v1:{hashlib.sha256(canonical.encode()).hexdigest()}"

    @staticmethod
    def _cache_hit(index: int, value: SearchQueryData) -> BatchItemResult[SearchQueryData]:
        cached = value.model_copy(
            update={
                "cache": value.cache.model_copy(update={"cached": True}),
                "usage": SearchUsageMetadata(),
            }
        )
        return BatchItemResult(index=index, outcome=LeafOutcome.SUCCEEDED, data=cached)

    @staticmethod
    def _error_item(
        index: int,
        outcome: LeafOutcome,
        category: ErrorCategory,
        code: str,
        message: str,
    ) -> BatchItemResult[SearchQueryData]:
        return BatchItemResult(
            index=index,
            outcome=outcome,
            error=OperationError(category=category, code=code, message=message),
        )


def _retry_reason(error: ProviderAttemptError) -> str:
    if error.stage is ExecutionStage.BEFORE_DISPATCH:
        return "pre_dispatch_failure"
    if error.error.category is ErrorCategory.TIMEOUT:
        return "timeout"
    if error.error.category is ErrorCategory.RATE_LIMITED:
        return "rate_limited"
    if error.stage is ExecutionStage.RESPONSE_LOST:
        return "response_lost"
    return "upstream_retryable"


def _billable_outcome(
    *, stage: AttemptStage, outcome_code: str | None, retry_reason: str | None
) -> str:
    if retry_reason is not None:
        return "retrying"
    if outcome_code == "succeeded":
        return "succeeded"
    if outcome_code is None:
        return "pending"
    if stage is AttemptStage.DISPATCH_POSSIBLE:
        return "unknown"
    return "failed"


def _aggregate_error(
    outcome: OperationOutcome,
    items: tuple[BatchItemResult[SearchQueryData], ...],
) -> OperationError:
    candidates = [item for item in items if item.error is not None]
    if outcome is OperationOutcome.UNKNOWN:
        candidates = [item for item in candidates if item.outcome is LeafOutcome.UNKNOWN]
    if not candidates:
        return OperationError(
            category=ErrorCategory.INTERNAL,
            code="search_batch_unsuccessful",
            message="Поисковая операция завершилась без успешных элементов.",
        )
    # Per-item order is authoritative. For a mixed no-success batch, the first
    # item matching the aggregate outcome deterministically supplies the broad error.
    selected = candidates[0].error
    if selected is None:
        raise RuntimeError("Search aggregate candidate has no error")
    return selected
