from __future__ import annotations

import pytest

from web_access.application.common.results import (
    ExecutionStage,
    automatic_retry_allowed,
)
from web_access.application.retrieval.retry import (
    RetrievalPhaseTracker,
    internal_fetch_retry_allowed,
)
from web_access.domain.retrieval import RetrievalExecutionPhase
from web_access.transport.mcp.retry import trusted_retry_descriptor


def test_retrieval_phase_model_covers_dispatch_resource_and_terminal_boundaries() -> None:
    tracker = RetrievalPhaseTracker()
    phases = tuple(RetrievalExecutionPhase)

    for phase in phases:
        tracker.advance(phase)
        if phase in {
            RetrievalExecutionPhase.VALIDATED,
            RetrievalExecutionPhase.DNS_RESOLVING,
            RetrievalExecutionPhase.CONNECTING,
        }:
            assert tracker.execution_stage is ExecutionStage.BEFORE_DISPATCH
        elif phase is RetrievalExecutionPhase.TERMINAL:
            assert tracker.execution_stage is ExecutionStage.TERMINAL_KNOWN
        elif phase.value.startswith("content_") or phase is RetrievalExecutionPhase.PROCESSING:
            assert tracker.execution_stage is ExecutionStage.SIDE_EFFECT_POSSIBLE
        else:
            assert tracker.execution_stage is ExecutionStage.DISPATCHED

    assert tracker.effects.resource_creation_possible is True
    with pytest.raises(ValueError, match="terminal"):
        tracker.advance(RetrievalExecutionPhase.VALIDATED)


def test_web_fetch_retry_requires_proven_pre_dispatch_phase() -> None:
    descriptor = trusted_retry_descriptor("web_fetch")
    assert descriptor is not None
    assert automatic_retry_allowed(
        retry_class=descriptor.retry_class,
        stage=ExecutionStage.BEFORE_DISPATCH,
        effects=descriptor.effects,
        error_retryable=True,
    )
    for stage in (
        ExecutionStage.DISPATCHED,
        ExecutionStage.SIDE_EFFECT_POSSIBLE,
        ExecutionStage.RESPONSE_LOST,
    ):
        assert not automatic_retry_allowed(
            retry_class=descriptor.retry_class,
            stage=stage,
            effects=descriptor.effects,
            error_retryable=True,
        )
    assert descriptor.blind_retry_after_possible_dispatch is False

    tracker = RetrievalPhaseTracker()
    tracker.advance(RetrievalExecutionPhase.CONNECTING)
    assert internal_fetch_retry_allowed(tracker, error_retryable=True)
    tracker.advance(RetrievalExecutionPhase.DISPATCH_POSSIBLE)
    assert not internal_fetch_retry_allowed(tracker, error_retryable=True)


def test_content_retry_descriptors_follow_r14_canonical_reuse_proof() -> None:
    content_get = trusted_retry_descriptor("content_get")
    content_parse = trusted_retry_descriptor("content_parse")
    assert content_get is not None
    assert content_parse is not None

    assert automatic_retry_allowed(
        retry_class=content_get.retry_class,
        stage=ExecutionStage.RESPONSE_LOST,
        effects=content_get.effects,
        error_retryable=True,
    )
    assert content_parse.idempotency_proven is True
    assert automatic_retry_allowed(
        retry_class=content_parse.retry_class,
        stage=ExecutionStage.RESPONSE_LOST,
        effects=content_parse.effects,
        error_retryable=True,
        idempotency_proven=content_parse.idempotency_proven,
    )
