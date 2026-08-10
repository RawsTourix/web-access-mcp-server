"""Correlation context lifecycle built on contextvars."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars


def bind_correlation(
    *,
    operation_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> None:
    values = {
        key: value
        for key, value in {
            "operation_id": operation_id,
            "request_id": request_id,
            "trace_id": trace_id,
        }.items()
        if value is not None
    }
    bind_contextvars(**values)


def clear_correlation() -> None:
    clear_contextvars()


def correlation_values() -> dict[str, object]:
    return dict(get_contextvars())


@contextmanager
def correlation_context(**values: str | None) -> Iterator[None]:
    clear_correlation()
    bind_correlation(
        operation_id=values.get("operation_id"),
        request_id=values.get("request_id"),
        trace_id=values.get("trace_id"),
    )
    try:
        yield
    finally:
        clear_correlation()
