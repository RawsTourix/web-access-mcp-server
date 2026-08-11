"""Retrieval-specific phase evidence for conservative internal retry decisions."""

from __future__ import annotations

from dataclasses import dataclass

from web_access.application.common.results import (
    ExecutionStage,
    OperationEffects,
    RetryClass,
    automatic_retry_allowed,
)
from web_access.domain.retrieval import RetrievalExecutionPhase

_ORDER = {phase: index for index, phase in enumerate(RetrievalExecutionPhase)}


@dataclass(slots=True)
class RetrievalPhaseTracker:
    phase: RetrievalExecutionPhase | None = None
    dispatch_possible: bool = False
    resource_creation_possible: bool = False

    def advance(self, phase: RetrievalExecutionPhase) -> None:
        if self.phase is RetrievalExecutionPhase.TERMINAL:
            raise ValueError("terminal Retrieval phase cannot advance")
        if self.phase is not None and _ORDER[phase] < _ORDER[self.phase]:
            raise ValueError("Retrieval phase cannot move backwards")
        self.phase = phase
        if _ORDER[phase] >= _ORDER[RetrievalExecutionPhase.DISPATCH_POSSIBLE]:
            self.dispatch_possible = True
        if _ORDER[phase] >= _ORDER[RetrievalExecutionPhase.CONTENT_CREATING]:
            self.resource_creation_possible = True

    @property
    def execution_stage(self) -> ExecutionStage:
        if self.phase is RetrievalExecutionPhase.TERMINAL:
            return ExecutionStage.TERMINAL_KNOWN
        if self.resource_creation_possible:
            return ExecutionStage.SIDE_EFFECT_POSSIBLE
        if self.dispatch_possible:
            return ExecutionStage.DISPATCHED
        return ExecutionStage.BEFORE_DISPATCH

    @property
    def effects(self) -> OperationEffects:
        return OperationEffects(resource_creation_possible=self.resource_creation_possible)

    @property
    def phase_value(self) -> str:
        return (
            self.phase.value if self.phase is not None else RetrievalExecutionPhase.VALIDATED.value
        )


def internal_fetch_retry_allowed(tracker: RetrievalPhaseTracker, *, error_retryable: bool) -> bool:
    """Permit same-Operation acquisition retry only with proven pre-dispatch evidence."""

    return automatic_retry_allowed(
        retry_class=RetryClass.PHASE_EVIDENCE_REQUIRED,
        stage=tracker.execution_stage,
        effects=tracker.effects,
        error_retryable=error_retryable,
    )
