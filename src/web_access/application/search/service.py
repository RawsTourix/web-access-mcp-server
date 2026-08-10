"""Framework-independent Search batch orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable
from dataclasses import dataclass
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
    SearchCache,
    SearchProvider,
    SearchSingleFlight,
    SearchUsageRepository,
    SingleFlightLease,
)
from web_access.application.search.registry import (
    ProviderResolutionError,
    SearchProviderRegistry,
    SearchRegionRegistry,
)
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

    def __post_init__(self) -> None:
        if self.cache_mode not in {"principal", "shared_public", "disabled"}:
            raise ValueError("invalid Search cache mode")
        if not 1 <= self.batch_concurrency <= 32:
            raise ValueError("invalid Search batch concurrency")
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


async def _bounded_await(context: ExecutionContext, awaitable: Awaitable[_T]) -> _T:
    remaining = context.remaining_seconds()
    if remaining is not None and remaining <= 0:
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[union-attr]
        raise _DeadlineExceeded
    if context.cancellation.requested:
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[union-attr]
        raise _CooperativeCancellation

    task = asyncio.ensure_future(awaitable)
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
        usage_repository: SearchUsageRepository | None,
        policy: SearchServicePolicy | None = None,
    ) -> None:
        self._providers = providers
        self._regions = regions
        self._cache = cache
        self._single_flight = single_flight
        self._rate = rate_limiter
        self._concurrency = concurrency_limiter
        self._usage = usage_repository
        self._policy = policy or SearchServicePolicy()

    async def search(
        self, context: ExecutionContext, request: SearchBatchRequest
    ) -> OperationResult[SearchBatchResult]:
        require_scope(context.principal, "search:read")
        semaphore = asyncio.Semaphore(self._policy.batch_concurrency)

        async def run(index: int, query: SearchQuery) -> BatchItemResult[SearchQueryData]:
            async with semaphore:
                return await self._search_item(context, index, query)

        pending = (run(index, query) for index, query in enumerate(request.queries))
        items = tuple(await asyncio.gather(*pending))
        outcome = aggregate_batch_outcome([item.outcome for item in items])
        error = None
        if outcome not in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
            error = OperationError(
                category=ErrorCategory.UNKNOWN_OUTCOME
                if outcome is OperationOutcome.UNKNOWN
                else ErrorCategory.UPSTREAM,
                code="search_batch_unsuccessful",
                message="Search batch did not contain a successful item.",
                retryable=False,
            )
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
                if cached.state is CacheLookupState.HIT and cached.value is not None:
                    return self._cache_hit(index, cached.value)
                lease = await _bounded_await(
                    context,
                    self._single_flight.acquire(identity, wait_seconds=context.remaining_seconds()),
                )
                if not lease.holder:
                    cached = await _bounded_await(context, self._cache.get(identity))
                    if cached.state is CacheLookupState.HIT and cached.value is not None:
                        return self._cache_hit(index, cached.value)
                    raise ProviderAttemptError(
                        OperationError(
                            category=ErrorCategory.CAPACITY,
                            code="single_flight_wait_exhausted",
                            message="Search single-flight wait was exhausted.",
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
                stored = await _bounded_await(
                    context,
                    self._cache.put(identity, data, self._policy.cache_ttl(provider_id)),
                )
                if not stored:
                    warnings.append(
                        Warning(
                            code="cache_write_failed",
                            message="Search result was obtained but could not be cached.",
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
                "Search item was cancelled.",
            )
        except _DeadlineExceeded:
            return self._error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.TIMEOUT,
                "search_deadline_exceeded",
                "Search item deadline was exceeded.",
            )
        finally:
            if lease is not None and lease.holder:
                await self._single_flight.release(lease)

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
            if not admission.allowed:
                raise ProviderAttemptError(
                    OperationError(
                        category=ErrorCategory.RATE_LIMITED,
                        code="provider_rate_limited",
                        message="Search provider rate limit denied the attempt.",
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
                raise ProviderAttemptError(
                    OperationError(
                        category=ErrorCategory.CAPACITY,
                        code="provider_capacity_unavailable",
                        message="Search provider capacity is unavailable.",
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
                                message="Billable Search accounting is unavailable.",
                            ),
                            stage=ExecutionStage.BEFORE_DISPATCH,
                        )
                    await _bounded_await(
                        context,
                        self._usage.start_attempt(
                            operation_id=context.operation_id,
                            principal_id=context.principal.principal_id,
                            provider_id=provider_id,
                            query_item_index=index,
                            attempt_number=attempt,
                        ),
                    )
                    await _bounded_await(
                        context,
                        self._usage.mark_stage(
                            operation_id=context.operation_id,
                            provider_id=provider_id,
                            query_item_index=index,
                            attempt_number=attempt,
                            stage=AttemptStage.DISPATCH_POSSIBLE,
                        ),
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
                except ProviderAttemptError as error:
                    if attempt < max_attempts and self._retry_allowed(
                        billable=descriptor.billable, error=error
                    ):
                        continue
                    raise
                if descriptor.billable and self._usage is not None:
                    await _bounded_await(
                        context,
                        self._usage.mark_stage(
                            operation_id=context.operation_id,
                            provider_id=provider_id,
                            query_item_index=index,
                            attempt_number=attempt,
                            stage=AttemptStage.COMPLETED,
                            outcome_code="succeeded",
                            provider_request_id=result.provider_request_id,
                        ),
                    )
                return result, attempt
            finally:
                await self._concurrency.release(concurrency)
        raise RuntimeError("unreachable Search attempt state")

    @staticmethod
    def _retry_allowed(*, billable: bool, error: ProviderAttemptError) -> bool:
        if not error.error.retryable:
            return False
        if billable:
            return error.stage is ExecutionStage.BEFORE_DISPATCH
        return True

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
