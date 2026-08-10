"""Optional OpenTelemetry provider and application-operation spans."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span

from web_access.core.config import ObservabilitySettings


def configure_tracing(
    settings: ObservabilitySettings,
    service_name: str,
    exporter: SpanExporter | None = None,
) -> TracerProvider | None:
    if not settings.tracing_enabled:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    selected_exporter = exporter
    if selected_exporter is None and settings.otlp_endpoint:
        try:
            selected_exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
        except Exception:  # Telemetry setup must not prevent the service from starting.
            selected_exporter = None
    if selected_exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(selected_exporter))
    return provider


def instrument_fastapi(app: FastAPI, provider: TracerProvider | None) -> None:
    """Instrument one app instance without installing a process-global provider."""

    if provider is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


@contextmanager
def operation_span(provider: TracerProvider | None, name: str) -> Iterator[Span | None]:
    if provider is None:
        yield None
        return
    tracer = provider.get_tracer("web_access.application")
    with tracer.start_as_current_span(name) as span:
        yield span


def shutdown_tracing(provider: TracerProvider | None) -> None:
    if provider is not None:
        provider.shutdown()
