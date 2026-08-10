from __future__ import annotations

from datetime import UTC, datetime

import pytest

from web_access.application.common.health import (
    Availability,
    DependencyProbe,
    HealthService,
)
from web_access.core.time import FakeClock


class MutableProbe:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return self.healthy


def _service(
    *, postgres: bool = True, redis: bool = True, content: bool = True
) -> tuple[HealthService, dict[str, MutableProbe]]:
    probes = {
        "postgres": MutableProbe(postgres),
        "redis": MutableProbe(redis),
        "content_store": MutableProbe(content),
    }
    service = HealthService(
        clock=FakeClock(datetime(2025, 1, 1, tzinfo=UTC)),
        probes=(
            DependencyProbe("postgres", True, probes["postgres"]),
            DependencyProbe("redis", False, probes["redis"]),
            DependencyProbe("content_store", True, probes["content_store"]),
        ),
    )
    service.mark_bootstrapped()
    return service, probes


@pytest.mark.asyncio
async def test_all_healthy_is_live_ready_and_safe() -> None:
    service, _ = _service()
    status = await service.status()
    assert service.liveness()
    assert status.status is Availability.READY
    assert status.runtime.ready
    assert status.capabilities == {}
    rendered = status.model_dump_json()
    assert "postgresql+asyncpg" not in rendered
    assert "redis://" not in rendered
    assert "filesystem" not in rendered


@pytest.mark.asyncio
async def test_mandatory_outage_is_unready_but_live() -> None:
    service, _ = _service(postgres=False)
    status = await service.status()
    assert service.liveness()
    assert not status.runtime.ready
    assert status.status is Availability.UNAVAILABLE


@pytest.mark.asyncio
async def test_optional_outage_is_degraded_but_ready() -> None:
    service, _ = _service(redis=False)
    status = await service.status()
    assert status.runtime.ready
    assert status.status is Availability.DEGRADED


@pytest.mark.asyncio
async def test_dependency_recovery_visible_without_restart() -> None:
    service, probes = _service(content=False)
    assert not await service.readiness()
    probes["content_store"].healthy = True
    status = await service.status()
    assert status.runtime.ready
    assert status.status is Availability.READY


@pytest.mark.asyncio
async def test_bootstrap_and_draining_are_distinct_from_liveness() -> None:
    probe = MutableProbe()
    service = HealthService(
        clock=FakeClock(datetime(2025, 1, 1, tzinfo=UTC)),
        probes=(DependencyProbe("postgres", True, probe),),
    )
    assert not await service.readiness()
    service.mark_bootstrapped()
    assert await service.readiness()
    service.begin_shutdown()
    assert not await service.readiness()
    assert service.liveness()
