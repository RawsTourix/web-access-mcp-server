"""Framework-independent correlation context based on stdlib contextvars."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_correlation: ContextVar[dict[str, str] | None] = ContextVar("web_access_correlation", default=None)


def bind_correlation(
    *, operation_id: str | None = None, request_id: str | None = None, trace_id: str | None = None
) -> None:
    values = dict(_correlation.get() or {})
    values.update(
        {
            key: value
            for key, value in {
                "operation_id": operation_id,
                "request_id": request_id,
                "trace_id": trace_id,
            }.items()
            if value is not None
        }
    )
    _correlation.set(values)


def clear_correlation() -> None:
    _correlation.set({})


def correlation_values() -> dict[str, object]:
    return dict(_correlation.get() or {})


@contextmanager
def correlation_context(**values: str | None) -> Iterator[None]:
    token = _correlation.set({})
    bind_correlation(
        operation_id=values.get("operation_id"),
        request_id=values.get("request_id"),
        trace_id=values.get("trace_id"),
    )
    try:
        yield
    finally:
        _correlation.reset(token)
