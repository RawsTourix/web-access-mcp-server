"""Application-level liveness, readiness, and dependency status model."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from web_access.core.time import Clock


class Availability(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    status: Availability
    mandatory: bool
    checked_at: datetime
    code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")


class RuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    live: bool
    ready: bool
    bootstrapped: bool
    draining: bool


class ServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Availability
    runtime: RuntimeStatus
    dependencies: tuple[DependencyStatus, ...]
    capabilities: dict[str, Availability] = Field(default_factory=dict)


Probe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class DependencyProbe:
    name: str
    mandatory: bool
    probe: Probe


class HealthService:
    """Current, side-effect-free health aggregation for one runtime profile."""

    def __init__(self, *, clock: Clock, probes: tuple[DependencyProbe, ...]) -> None:
        names = [probe.name for probe in probes]
        if len(set(names)) != len(names):
            raise ValueError("dependency probe names must be unique")
        self._clock = clock
        self._probes = probes
        self._bootstrapped = False
        self._draining = False

    def mark_bootstrapped(self) -> None:
        self._bootstrapped = True

    def begin_shutdown(self) -> None:
        self._draining = True

    def liveness(self) -> bool:
        """Dependency failures never make the event-loop runtime dead."""

        return True

    async def status(self) -> ServiceStatus:
        checks = await asyncio.gather(*(probe.probe() for probe in self._probes))
        checked_at = self._clock.utc_now()
        dependencies = tuple(
            DependencyStatus(
                name=probe.name,
                status=Availability.READY if healthy else Availability.UNAVAILABLE,
                mandatory=probe.mandatory,
                checked_at=checked_at,
                code=None if healthy else "probe_failed",
            )
            for probe, healthy in zip(self._probes, checks, strict=True)
        )
        mandatory_ready = all(
            dependency.status is Availability.READY
            for dependency in dependencies
            if dependency.mandatory
        )
        runtime_ready = self._bootstrapped and not self._draining and mandatory_ready
        if not runtime_ready:
            availability = Availability.UNAVAILABLE
        elif any(dependency.status is Availability.UNAVAILABLE for dependency in dependencies):
            availability = Availability.DEGRADED
        else:
            availability = Availability.READY
        return ServiceStatus(
            status=availability,
            runtime=RuntimeStatus(
                live=True,
                ready=runtime_ready,
                bootstrapped=self._bootstrapped,
                draining=self._draining,
            ),
            dependencies=dependencies,
        )

    async def readiness(self) -> bool:
        return (await self.status()).runtime.ready
