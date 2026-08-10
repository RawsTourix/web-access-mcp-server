from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from io import StringIO

import httpx
import pytest
import structlog
from fastapi import FastAPI
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from web_access.core.config import ObservabilitySettings
from web_access.infrastructure.observability import (
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
