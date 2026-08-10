"""Canonical operation outcomes, results, batch aggregation, and retry policy."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from web_access.application.common.errors import OperationError, PublicError
from web_access.application.common.hints import StructuredHint, Warning


class OperationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class PublicOperationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class LeafOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class CompoundStepOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


def public_outcome(outcome: OperationOutcome) -> PublicOperationOutcome:
    if outcome is OperationOutcome.PARTIAL_SUCCESS:
        return PublicOperationOutcome.PARTIAL
    return PublicOperationOutcome(outcome.value)


DataT = TypeVar("DataT")


class OperationResult(BaseModel, Generic[DataT]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    outcome: OperationOutcome
    data: DataT | None = None
    error: OperationError | None = None
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_outcome(self) -> OperationResult[DataT]:
        if self.outcome in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
            if self.error is not None:
                raise ValueError("successful or partial result cannot have a primary error")
        elif self.error is None:
            raise ValueError("non-success result requires a normalized error")
        return self


class PublicOperationResult(BaseModel, Generic[DataT]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    outcome: PublicOperationOutcome
    data: DataT | None = None
    error: PublicError | None = None
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)


def project_result(result: OperationResult[DataT]) -> PublicOperationResult[DataT]:
    return PublicOperationResult[DataT](
        operation_id=result.operation_id,
        outcome=public_outcome(result.outcome),
        data=result.data,
        error=result.error,
        warnings=result.warnings,
        hints=result.hints,
    )


class BatchItemResult(BaseModel, Generic[DataT]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    outcome: LeafOutcome
    data: DataT | None = None
    error: PublicError | None = None
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_outcome(self) -> BatchItemResult[DataT]:
        if self.outcome is LeafOutcome.SUCCEEDED and self.error is not None:
            raise ValueError("successful item cannot have an error")
        if self.outcome is not LeafOutcome.SUCCEEDED and self.error is None:
            raise ValueError("non-success item requires an error")
        return self


def aggregate_batch_outcome(outcomes: list[LeafOutcome]) -> OperationOutcome:
    if not outcomes:
        raise ValueError("batch must contain at least one item")
    if all(outcome is LeafOutcome.SUCCEEDED for outcome in outcomes):
        return OperationOutcome.SUCCEEDED
    if any(outcome is LeafOutcome.SUCCEEDED for outcome in outcomes):
        return OperationOutcome.PARTIAL_SUCCESS
    if any(outcome is LeafOutcome.UNKNOWN for outcome in outcomes):
        return OperationOutcome.UNKNOWN
    if all(outcome is LeafOutcome.REJECTED for outcome in outcomes):
        return OperationOutcome.REJECTED
    if all(outcome is LeafOutcome.CANCELLED for outcome in outcomes):
        return OperationOutcome.CANCELLED
    return OperationOutcome.FAILED


def ordered_batch_items(items: list[BatchItemResult[DataT]]) -> list[BatchItemResult[DataT]]:
    indexes = [item.index for item in items]
    if len(set(indexes)) != len(indexes):
        raise ValueError("batch item indexes must be unique")
    return sorted(items, key=lambda item: item.index)


class RetryClass(StrEnum):
    SAFE_RETRY = "safe_retry"
    IDEMPOTENT_RETRY = "idempotent_retry"
    NEVER_AUTOMATIC = "never_automatic"
    PHASE_EVIDENCE_REQUIRED = "phase_evidence_required"


class ExecutionStage(StrEnum):
    BEFORE_DISPATCH = "before_dispatch"
    DISPATCHED = "dispatched"
    EXECUTING = "executing"
    SIDE_EFFECT_POSSIBLE = "side_effect_possible"
    TERMINAL_KNOWN = "terminal_known"
    RESPONSE_LOST = "response_lost"


class OperationEffects(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    billable_cost_possible: bool = False
    resource_creation_possible: bool = False
    external_side_effect_possible: bool = False


def automatic_retry_allowed(
    *,
    retry_class: RetryClass,
    stage: ExecutionStage,
    effects: OperationEffects,
    error_retryable: bool,
    idempotency_proven: bool = False,
) -> bool:
    """Apply the most conservative retry evidence; retryable alone is insufficient."""

    if not error_retryable or stage in {
        ExecutionStage.SIDE_EFFECT_POSSIBLE,
        ExecutionStage.RESPONSE_LOST,
    }:
        return False
    if retry_class is RetryClass.NEVER_AUTOMATIC:
        return False
    if retry_class is RetryClass.IDEMPOTENT_RETRY:
        return idempotency_proven
    if retry_class is RetryClass.PHASE_EVIDENCE_REQUIRED:
        return stage is ExecutionStage.BEFORE_DISPATCH and not any(
            (
                effects.billable_cost_possible,
                effects.resource_creation_possible,
                effects.external_side_effect_possible,
            )
        )
    return not any(
        (
            effects.billable_cost_possible,
            effects.resource_creation_possible,
            effects.external_side_effect_possible,
        )
    )
