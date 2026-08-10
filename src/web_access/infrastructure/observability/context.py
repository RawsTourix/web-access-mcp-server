"""Compatibility exports for application-owned correlation primitives."""

from web_access.application.common.correlation import (
    bind_correlation,
    clear_correlation,
    correlation_context,
    correlation_values,
)

__all__ = [
    "bind_correlation",
    "clear_correlation",
    "correlation_context",
    "correlation_values",
]
