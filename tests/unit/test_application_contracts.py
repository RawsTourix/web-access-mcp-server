from __future__ import annotations

from datetime import UTC, datetime
from itertools import product

import pytest
from pydantic import ValidationError

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory, FieldError, OperationError
from web_access.application.common.hints import StructuredHint, Warning
from web_access.application.common.results import (
    BatchItemResult,
    CompoundStepOutcome,
    ExecutionStage,
    LeafOutcome,
    OperationEffects,
    OperationOutcome,
    OperationResult,
    PublicOperationOutcome,
    RetryClass,
    aggregate_batch_outcome,
    automatic_retry_allowed,
    ordered_batch_items,
    project_result,
)
from web_access.core.time import Deadline, FakeClock


def _error(retryable: bool = False) -> OperationError:
    return OperationError(
        category=ErrorCategory.VALIDATION,
        code="invalid_arguments",
        message="Некорректные аргументы.",
        retryable=retryable,
        fields=(FieldError(path="items[0]", code="invalid", message="Исправьте поле."),),
    )


def test_operation_result_invariants_and_public_projection() -> None:
    partial = OperationResult[dict[str, str]](
        operation_id=f"op_{'1' * 32}",
        outcome=OperationOutcome.PARTIAL_SUCCESS,
        data={"useful": "evidence"},
    )
    projected = project_result(partial)
    assert projected.outcome is PublicOperationOutcome.PARTIAL
    assert projected.model_dump(mode="json")["outcome"] == "partial"
    assert "partial_success" not in projected.model_dump_json()
    with pytest.raises(ValidationError):
        OperationResult[None](
            operation_id=f"op_{'2' * 32}",
            outcome=OperationOutcome.FAILED,
        )
    with pytest.raises(ValidationError):
        OperationResult[None](
            operation_id=f"op_{'3' * 32}",
            outcome=OperationOutcome.SUCCEEDED,
            error=_error(),
        )


def test_unknown_is_preserved() -> None:
    result = OperationResult[None](
        operation_id=f"op_{'4' * 32}",
        outcome=OperationOutcome.UNKNOWN,
        error=OperationError(
            category=ErrorCategory.UNKNOWN_OUTCOME,
            code="response_lost",
            message="Результат выполнения неизвестен.",
        ),
    )
    assert project_result(result).outcome is PublicOperationOutcome.UNKNOWN


def test_batch_aggregate_all_combinations() -> None:
    leaves = list(LeafOutcome)
    for size in (1, 2, 3):
        for combination in product(leaves, repeat=size):
            outcome = aggregate_batch_outcome(list(combination))
            if all(item is LeafOutcome.SUCCEEDED for item in combination):
                assert outcome is OperationOutcome.SUCCEEDED
            elif LeafOutcome.SUCCEEDED in combination:
                assert outcome is OperationOutcome.PARTIAL_SUCCESS
            elif LeafOutcome.UNKNOWN in combination:
                assert outcome is OperationOutcome.UNKNOWN
            elif all(item is LeafOutcome.REJECTED for item in combination):
                assert outcome is OperationOutcome.REJECTED
            elif all(item is LeafOutcome.CANCELLED for item in combination):
                assert outcome is OperationOutcome.CANCELLED
            else:
                assert outcome is OperationOutcome.FAILED
    with pytest.raises(ValueError, match="at least one"):
        aggregate_batch_outcome([])


def test_batch_order_is_stable_and_index_driven() -> None:
    items = [
        BatchItemResult[str](index=1, outcome=LeafOutcome.SUCCEEDED, data="second"),
        BatchItemResult[str](index=0, outcome=LeafOutcome.SUCCEEDED, data="first"),
    ]
    assert [item.data for item in ordered_batch_items(items)] == ["first", "second"]


def test_not_attempted_is_separate_from_operation_outcome() -> None:
    assert CompoundStepOutcome.NOT_ATTEMPTED.value == "not_attempted"
    assert "not_attempted" not in {outcome.value for outcome in OperationOutcome}


def test_warning_hint_and_error_have_distinct_semantics() -> None:
    warning = Warning(code="truncated", message="Результат усечён.")
    hint = StructuredHint(
        code="browser_may_be_required",
        message="Может потребоваться браузер.",
        related_capability="browser",
    )
    result = OperationResult[str](
        operation_id=f"op_{'5' * 32}",
        outcome=OperationOutcome.SUCCEEDED,
        data="bounded",
        warnings=(warning,),
        hints=(hint,),
    )
    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.error is None


@pytest.mark.asyncio
async def test_cancellation_and_deadline_propagation() -> None:
    clock = FakeClock(datetime(2025, 1, 1, tzinfo=UTC))
    cancellation = CancellationToken()
    context = ExecutionContext(
        operation_id=f"op_{'6' * 32}",
        principal=PrincipalContext("agent", frozenset({"read"})),
        clock=clock,
        cancellation=cancellation,
        deadline=Deadline.after(clock, 5),
    )
    assert context.downstream_deadline(10).remaining(clock) == 5
    assert not cancellation.requested
    cancellation.request()
    await cancellation.wait()
    assert cancellation.requested


def test_retryable_does_not_override_cost_or_resource_effects() -> None:
    error = _error(retryable=True)
    assert error.retryable
    assert not automatic_retry_allowed(
        retry_class=RetryClass.SAFE_RETRY,
        stage=ExecutionStage.DISPATCHED,
        effects=OperationEffects(resource_creation_possible=True),
        error_retryable=error.retryable,
    )
    assert not automatic_retry_allowed(
        retry_class=RetryClass.NEVER_AUTOMATIC,
        stage=ExecutionStage.BEFORE_DISPATCH,
        effects=OperationEffects(),
        error_retryable=True,
    )
    assert automatic_retry_allowed(
        retry_class=RetryClass.IDEMPOTENT_RETRY,
        stage=ExecutionStage.TERMINAL_KNOWN,
        effects=OperationEffects(resource_creation_possible=True),
        error_retryable=True,
        idempotency_proven=True,
    )


def test_phase_evidence_allows_pre_dispatch_retry_despite_future_effects() -> None:
    assert automatic_retry_allowed(
        retry_class=RetryClass.PHASE_EVIDENCE_REQUIRED,
        stage=ExecutionStage.BEFORE_DISPATCH,
        effects=OperationEffects(
            billable_cost_possible=True,
            resource_creation_possible=True,
            external_side_effect_possible=True,
        ),
        error_retryable=True,
    )


def test_retry_policy_exhaustive_decision_table() -> None:
    ambiguous_stages = {
        ExecutionStage.DISPATCHED,
        ExecutionStage.EXECUTING,
        ExecutionStage.SIDE_EFFECT_POSSIBLE,
        ExecutionStage.RESPONSE_LOST,
    }
    cases = 0
    for retry_class, stage, effect_values, error_retryable, idempotency_proven in product(
        RetryClass,
        ExecutionStage,
        product((False, True), repeat=3),
        (False, True),
        (False, True),
    ):
        effects = OperationEffects(
            billable_cost_possible=effect_values[0],
            resource_creation_possible=effect_values[1],
            external_side_effect_possible=effect_values[2],
        )
        has_effect = any(effect_values)
        if not error_retryable or retry_class is RetryClass.NEVER_AUTOMATIC:
            expected = False
        elif stage in ambiguous_stages and has_effect:
            expected = False
        elif retry_class is RetryClass.IDEMPOTENT_RETRY:
            expected = idempotency_proven
        elif retry_class is RetryClass.PHASE_EVIDENCE_REQUIRED:
            expected = stage is ExecutionStage.BEFORE_DISPATCH
        else:
            expected = not has_effect
        assert (
            automatic_retry_allowed(
                retry_class=retry_class,
                stage=stage,
                effects=effects,
                error_retryable=error_retryable,
                idempotency_proven=idempotency_proven,
            )
            is expected
        )
        cases += 1
    assert cases == 768
