from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from io import StringIO

import httpx
import pytest
import structlog
from fastapi import FastAPI
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory, OperationError
from web_access.application.common.results import ExecutionStage
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
)
from web_access.application.search.ports import (
    AttemptStage,
    CacheLookupState,
    ProviderAttemptError,
)
from web_access.core.config import ObservabilitySettings
from web_access.core.time import FakeClock
from web_access.domain.search import SearchProviderId, SearchResultItem
from web_access.infrastructure.observability import (
    ObservedSearchProvider,
    SearchTelemetryAdapter,
    bind_correlation,
    clear_correlation,
    configure_logging,
    configure_tracing,
    correlation_values,
    create_metrics,
    instrument_fastapi,
    operation_span,
    shutdown_tracing,
)


class ObservableProvider:
    descriptor = ProviderDescriptor(
        provider_id=SearchProviderId.SEARXNG,
        name="SearXNG",
        enabled=True,
        configuration_revision="observable-revision",
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

    def __init__(self, *, failure: ProviderAttemptError | None = None) -> None:
        self.failure = failure

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = request
        context.clock.advance(0.25)  # type: ignore[attr-defined]
        if self.failure is not None:
            raise self.failure
        return ProviderSearchResult(
            provider_id=SearchProviderId.SEARXNG,
            results=(
                SearchResultItem(
                    rank=1,
                    title="secret-title-canary",
                    url="https://secret-url-canary.example",
                ),
            ),
            retrieved_at=context.clock.utc_now(),
        )


def _search_context() -> ExecutionContext:
    return ExecutionContext(
        operation_id="safe-operation",
        principal=PrincipalContext("secret-principal-canary", frozenset({"search:read"})),
        clock=FakeClock(datetime(2026, 8, 11, tzinfo=UTC)),
        cancellation=CancellationToken(),
    )


def _provider_request() -> ProviderSearchRequest:
    return ProviderSearchRequest(
        query="secret-query-canary",
        provider_id=SearchProviderId.SEARXNG,
        page=1,
        limit=1,
    )


def test_json_logging_correlation_and_recursive_redaction() -> None:
    stream = StringIO()
    configure_logging(ObservabilitySettings(log_format="json"), stream)
    clear_correlation()
    bind_correlation(operation_id="op_safe", request_id="req_safe", trace_id="trace_safe")
    structlog.get_logger().info(
        "foundation_event",
        authorization="Bearer raw-secret",
        nested={"password": "raw-password", "safe": "value"},
        body=b"raw-content",
    )
    event = json.loads(stream.getvalue())
    assert event["event"] == "foundation_event"
    assert event["operation_id"] == "op_safe"
    assert event["request_id"] == "req_safe"
    assert event["trace_id"] == "trace_safe"
    rendered = stream.getvalue()
    assert "raw-secret" not in rendered
    assert "raw-password" not in rendered
    assert "raw-content" not in rendered
    assert event["nested"]["safe"] == "value"
    clear_correlation()
    assert correlation_values() == {}


def test_stdlib_logging_uses_same_json_pipeline() -> None:
    stream = StringIO()
    configure_logging(ObservabilitySettings(log_format="json"), stream)
    logging.getLogger("dependency").warning("dependency warning")
    assert json.loads(stream.getvalue())["event"] == "dependency warning"


def test_metrics_registries_are_isolated_and_low_cardinality() -> None:
    first = create_metrics()
    second = create_metrics()
    first.requests.labels(method="GET", route="/health/live", status_class="2xx").inc()
    assert b'route="/health/live"' in first.render()
    assert b'route="/health/live"' not in second.render()
    label_names = set(first.requests._labelnames)
    assert label_names == {"method", "route", "status_class"}
    assert not label_names & {"operation_id", "request_id", "principal_id", "url", "query"}


def test_search_metrics_use_only_bounded_labels() -> None:
    metrics = create_metrics()
    telemetry = SearchTelemetryAdapter(metrics)
    telemetry.observe_cache(SearchProviderId.SEARXNG, CacheLookupState.HIT)
    telemetry.observe_cache(SearchProviderId.SEARXNG, CacheLookupState.CORRUPT)
    telemetry.observe_admission_rejection(SearchProviderId.SEARXNG, "rate")
    telemetry.observe_admission_rejection(SearchProviderId.YANDEX, "concurrency")
    telemetry.observe_internal_retry(SearchProviderId.SEARXNG, "timeout")
    telemetry.observe_billable_attempt(
        SearchProviderId.YANDEX, AttemptStage.DISPATCH_POSSIBLE, "pending"
    )
    telemetry.observe_provider_readiness(SearchProviderId.SEARXNG, "ready")
    rendered = metrics.render().decode()
    for expected in (
        "web_access_search_cache_total",
        'provider="searxng"',
        'state="hit"',
        'kind="rate"',
        'reason="timeout"',
        'stage="dispatch_possible"',
        'status="ready"',
    ):
        assert expected in rendered
    for forbidden in (
        "secret-query-canary",
        "secret-url-canary",
        "secret-principal-canary",
        "authorization",
        "folder_id",
    ):
        assert forbidden not in rendered.lower()


@pytest.mark.asyncio
async def test_observed_provider_records_safe_metrics_logs_and_spans() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    metrics = create_metrics()
    provider = ObservedSearchProvider(
        ObservableProvider(), metrics=metrics, tracer_provider=tracer_provider
    )
    result = await provider.search(_search_context(), _provider_request())
    assert len(result.results) == 1
    rendered = metrics.render().decode()
    assert "web_access_search_provider_calls_total" in rendered
    assert 'provider="searxng"' in rendered and 'outcome="succeeded"' in rendered
    assert "web_access_search_result_count_sum" in rendered
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["search.provider_attempt"]
    attributes = repr(spans[0].attributes)
    assert "search.provider_id" in attributes and "search.result_count" in attributes
    assert "secret-query-canary" not in attributes
    assert "secret-url-canary" not in attributes
    assert "secret-principal-canary" not in attributes
    shutdown_tracing(tracer_provider)


@pytest.mark.asyncio
async def test_observed_provider_normalizes_failure_log_without_query_or_body() -> None:
    failure = ProviderAttemptError(
        OperationError(
            category=ErrorCategory.TIMEOUT,
            code="provider_timeout",
            message="safe timeout",
            retryable=True,
        ),
        stage=ExecutionStage.RESPONSE_LOST,
    )
    metrics = create_metrics()
    provider = ObservedSearchProvider(
        ObservableProvider(failure=failure), metrics=metrics, tracer_provider=None
    )
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(ProviderAttemptError):
            await provider.search(_search_context(), _provider_request())
    rendered = repr(logs)
    assert "provider_timeout" in rendered
    assert "secret-query-canary" not in rendered
    assert "secret-url-canary" not in rendered
    assert "secret-principal-canary" not in rendered
    metrics_text = metrics.render().decode()
    assert "web_access_search_provider_timeouts_total" in metrics_text


class FailingExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.FAILURE


def test_tracing_disabled_and_exporter_failure_are_non_fatal() -> None:
    assert configure_tracing(ObservabilitySettings(tracing_enabled=False), "web-access") is None
    provider = configure_tracing(
        ObservabilitySettings(tracing_enabled=True),
        "web-access",
        FailingExporter(),
    )
    assert provider is not None
    with operation_span(provider, "foundation.operation") as span:
        assert span is not None
        span.set_attribute("bounded.kind", "foundation")
    shutdown_tracing(provider)


@pytest.mark.asyncio
async def test_fastapi_instrumentation_is_isolated_per_app_instance() -> None:
    exporters = (InMemorySpanExporter(), InMemorySpanExporter())
    providers = (TracerProvider(), TracerProvider())
    apps = (FastAPI(), FastAPI())
    for index, (app, provider, exporter) in enumerate(zip(apps, providers, exporters, strict=True)):
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        @app.get(f"/app-{index}")
        async def endpoint() -> dict[str, bool]:
            return {"ok": True}

        instrument_fastapi(app, provider)

    for index, app in enumerate(apps):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get(f"/app-{index}")).status_code == 200

    first_names = {span.name for span in exporters[0].get_finished_spans()}
    second_names = {span.name for span in exporters[1].get_finished_spans()}
    assert any("/app-0" in name for name in first_names)
    assert not any("/app-1" in name for name in first_names)
    assert any("/app-1" in name for name in second_names)
    assert not any("/app-0" in name for name in second_names)
    for provider in providers:
        shutdown_tracing(provider)
