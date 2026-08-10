from collections.abc import Iterator

import pytest

from web_access.core.ids import (
    DeterministicIdGenerator,
    IdPrefix,
    Uuid4IdGenerator,
    is_valid_id,
)


def test_uuid4_generator_has_canonical_shape() -> None:
    value = Uuid4IdGenerator().new(IdPrefix.OPERATION)
    assert is_valid_id(value, IdPrefix.OPERATION)


def test_deterministic_generator() -> None:
    values: Iterator[str] = iter(["0" * 32])
    assert DeterministicIdGenerator(values).new(IdPrefix.OPERATION) == f"op_{'0' * 32}"


def test_deterministic_generator_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="32 lowercase"):
        DeterministicIdGenerator(iter(["invalid"])).new(IdPrefix.OPERATION)
