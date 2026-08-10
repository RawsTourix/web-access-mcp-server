"""Framework-independent execution and principal context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from web_access.core.time import Clock, Deadline


class PrincipalType(StrEnum):
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Trusted identity constructed exclusively by an AuthProvider."""

    principal_id: str
    scopes: frozenset[str]
    principal_type: PrincipalType = PrincipalType.SERVICE
    registry_revision: str | None = None


class CancellationContext(Protocol):
    @property
    def requested(self) -> bool:
        """Whether cooperative cancellation has been requested."""
        ...

    async def wait(self) -> None:
        """Wait until cancellation is requested."""
        ...


@dataclass(slots=True)
class CancellationToken:
    """Small asyncio-backed cancellation primitive without Task coupling."""

    _event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    operation_id: str
    principal: PrincipalContext
    clock: Clock
    cancellation: CancellationContext
    deadline: Deadline | None = None
    request_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    policy_revision: str | None = None

    def remaining_seconds(self) -> float | None:
        return None if self.deadline is None else self.deadline.remaining(self.clock)

    def downstream_deadline(self, timeout_seconds: float) -> Deadline:
        requested = Deadline.after(self.clock, timeout_seconds)
        return (
            requested if self.deadline is None else self.deadline.child(self.clock, timeout_seconds)
        )
