"""Trusted server-owned retry metadata for production MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from web_access.application.common.results import OperationEffects, RetryClass


@dataclass(frozen=True, slots=True)
class TrustedToolRetryDescriptor:
    retry_class: RetryClass
    effects: OperationEffects
    blind_retry_after_possible_dispatch: bool
    idempotency_proven: bool = False


_DESCRIPTORS = MappingProxyType(
    {
        "web_search": TrustedToolRetryDescriptor(
            retry_class=RetryClass.PHASE_EVIDENCE_REQUIRED,
            effects=OperationEffects(billable_cost_possible=True),
            blind_retry_after_possible_dispatch=False,
        ),
        "web_fetch": TrustedToolRetryDescriptor(
            retry_class=RetryClass.PHASE_EVIDENCE_REQUIRED,
            effects=OperationEffects(resource_creation_possible=True),
            blind_retry_after_possible_dispatch=False,
        ),
        "content_get": TrustedToolRetryDescriptor(
            retry_class=RetryClass.SAFE_RETRY,
            effects=OperationEffects(),
            blind_retry_after_possible_dispatch=True,
        ),
        "content_parse": TrustedToolRetryDescriptor(
            retry_class=RetryClass.IDEMPOTENT_RETRY,
            effects=OperationEffects(resource_creation_possible=True),
            blind_retry_after_possible_dispatch=True,
            idempotency_proven=True,
        ),
    }
)


def trusted_retry_descriptor(tool_name: str) -> TrustedToolRetryDescriptor | None:
    """Return trusted integration metadata; callers cannot supply or alter it."""

    return _DESCRIPTORS.get(tool_name)
