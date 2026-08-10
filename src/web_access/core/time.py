"""Injectable UTC wall time and monotonic deadline primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Protocol, Self


class Clock(Protocol):
    """Clock contract separating timestamps from elapsed-time measurement."""

    def utc_now(self) -> datetime:
        """Return a timezone-aware UTC timestamp."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic time point in seconds."""
        ...


class SystemClock:
    """Production clock."""

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return monotonic()


@dataclass(slots=True)
class FakeClock:
    """Deterministic clock for lifecycle and deadline tests."""

    wall_time: datetime
    monotonic_time: float = 0.0

    def __post_init__(self) -> None:
        if self.wall_time.tzinfo is None or self.wall_time.utcoffset() is None:
            raise ValueError("fake wall clock must be timezone-aware")
        self.wall_time = self.wall_time.astimezone(UTC)

    def utc_now(self) -> datetime:
        return self.wall_time

    def monotonic(self) -> float:
        return self.monotonic_time

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("clock cannot move backwards")
        self.monotonic_time += seconds
        self.wall_time += timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class Deadline:
    """Absolute monotonic deadline."""

    expires_at: float

    @classmethod
    def after(cls, clock: Clock, timeout_seconds: float) -> Self:
        if timeout_seconds < 0:
            raise ValueError("timeout must not be negative")
        return cls(clock.monotonic() + timeout_seconds)

    def remaining(self, clock: Clock) -> float:
        return max(0.0, self.expires_at - clock.monotonic())

    def expired(self, clock: Clock) -> bool:
        return self.remaining(clock) == 0.0

    def child(self, clock: Clock, timeout_seconds: float) -> Self:
        """Return a deadline that never exceeds the remaining parent budget."""

        return type(self)(min(self.expires_at, Deadline.after(clock, timeout_seconds).expires_at))
