"""Low-cardinality Search metrics, logs, and provider-attempt spans."""

from __future__ import annotations

import structlog
from opentelemetry.sdk.trace import TracerProvider

from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import ErrorCategory
from web_access.application.search.models import (
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
)
from web_access.application.search.ports import (
    AttemptStage,
    CacheLookupState,
    ProviderAttemptError,
    SearchProvider,
)
from web_access.domain.search import SearchProviderId
from web_access.infrastructure.observability.metrics import ServiceMetrics
from web_access.infrastructure.observability.tracing import operation_span


class SearchTelemetryAdapter:
    def __init__(self, metrics: ServiceMetrics) -> None:
        self._metrics = metrics

    def observe_cache(self, provider_id: SearchProviderId, state: CacheLookupState) -> None:
        self._metrics.observe_search_cache(provider=provider_id.value, state=state.value)

    def observe_admission_rejection(self, provider_id: SearchProviderId, kind: str) -> None:
        self._metrics.observe_search_admission_rejection(provider=provider_id.value, kind=kind)

    def observe_internal_retry(self, provider_id: SearchProviderId, reason: str) -> None:
        self._metrics.observe_search_retry(provider=provider_id.value, reason=reason)

    def observe_billable_attempt(
        self, provider_id: SearchProviderId, stage: AttemptStage, outcome: str
    ) -> None:
        self._metrics.observe_search_billable_attempt(
            provider=provider_id.value, stage=stage.value, outcome=outcome
        )

    def observe_provider_readiness(self, provider_id: SearchProviderId, status: str) -> None:
        self._metrics.set_search_provider_readiness(provider=provider_id.value, status=status)


class ObservedSearchProvider:
    """Decorator that never records query text, URLs, principals, or response bodies."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        metrics: ServiceMetrics,
        tracer_provider: TracerProvider | None,
    ) -> None:
        self._provider = provider
        self._metrics = metrics
        self._tracer_provider = tracer_provider
        self._logger = structlog.get_logger(__name__)

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._provider.descriptor

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        provider = self.descriptor.provider_id.value
        started = context.clock.monotonic()
        with operation_span(self._tracer_provider, "search.provider_attempt") as span:
            if span is not None:
                span.set_attribute("search.provider_id", provider)
            try:
                result = await self._provider.search(context, request)
            except ProviderAttemptError as error:
                duration = max(0.0, context.clock.monotonic() - started)
                outcome = (
                    "unknown" if error.error.category is ErrorCategory.UNKNOWN_OUTCOME else "failed"
                )
                timed_out = error.error.category is ErrorCategory.TIMEOUT
                self._metrics.observe_search_provider_call(
                    provider=provider,
                    outcome=outcome,
                    duration_seconds=duration,
                    result_count=None,
                    timed_out=timed_out,
                )
                if span is not None:
                    span.set_attribute("search.outcome", outcome)
                    span.set_attribute("search.error_code", error.error.code)
                self._logger.warning(
                    "search_provider_failed",
                    provider_id=provider,
                    error_category=error.error.category.value,
                    error_code=error.error.code,
                    attempt_outcome=outcome,
                )
                raise
            except BaseException:
                duration = max(0.0, context.clock.monotonic() - started)
                self._metrics.observe_search_provider_call(
                    provider=provider,
                    outcome="cancelled",
                    duration_seconds=duration,
                    result_count=None,
                    timed_out=False,
                )
                if span is not None:
                    span.set_attribute("search.outcome", "cancelled")
                raise
            duration = max(0.0, context.clock.monotonic() - started)
            self._metrics.observe_search_provider_call(
                provider=provider,
                outcome="succeeded",
                duration_seconds=duration,
                result_count=len(result.results),
                timed_out=False,
            )
            if span is not None:
                span.set_attribute("search.outcome", "succeeded")
                span.set_attribute("search.result_count", len(result.results))
            return result
