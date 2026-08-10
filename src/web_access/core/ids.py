"""Canonical opaque identifier generation."""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Protocol
from uuid import uuid4


class IdPrefix(StrEnum):
    """Known foundation identifier type guards."""

    OPERATION = "op"


class IdGenerator(Protocol):
    """Injectable opaque identifier source."""

    def new(self, prefix: IdPrefix) -> str:
        """Return a new opaque identifier carrying only a type prefix."""
        ...


class Uuid4IdGenerator:
    """Production generator based on random UUID4 hex values."""

    def new(self, prefix: IdPrefix) -> str:
        return f"{prefix.value}_{uuid4().hex}"


class DeterministicIdGenerator:
    """Finite deterministic generator intended for tests."""

    def __init__(self, values: Iterator[str]) -> None:
        self._values = values

    def new(self, prefix: IdPrefix) -> str:
        value = next(self._values)
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("deterministic ID values must be 32 lowercase hexadecimal characters")
        return f"{prefix.value}_{value}"


def is_valid_id(value: str, prefix: IdPrefix) -> bool:
    """Validate syntax without assigning authority to the prefix."""

    expected = f"{prefix.value}_"
    suffix = value.removeprefix(expected)
    return (
        value.startswith(expected)
        and len(suffix) == 32
        and all(character in "0123456789abcdef" for character in suffix)
    )
