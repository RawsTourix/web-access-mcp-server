"""Observability adapters."""

from web_access.infrastructure.observability.context import (
    bind_correlation,
    clear_correlation,
    correlation_context,
    correlation_values,
)
from web_access.infrastructure.observability.logging import configure_logging
from web_access.infrastructure.observability.metrics import ServiceMetrics, create_metrics
from web_access.infrastructure.observability.tracing import (
    configure_tracing,
    operation_span,
    shutdown_tracing,
)

__all__ = [
    "ServiceMetrics",
    "bind_correlation",
    "clear_correlation",
    "configure_logging",
    "configure_tracing",
    "correlation_context",
    "correlation_values",
    "create_metrics",
    "operation_span",
    "shutdown_tracing",
]
