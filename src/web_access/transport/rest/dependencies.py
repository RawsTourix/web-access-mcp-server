"""Structural dependency view supplied by bootstrap to REST."""

from __future__ import annotations

from typing import Protocol, cast

from fastapi import Request

from web_access.application.common.auth import AuthProvider
from web_access.application.common.health import HealthService
from web_access.application.common.observability import Metrics
from web_access.application.search.readiness import SearchProviderReadinessService
from web_access.application.search.service import SearchApplicationService
from web_access.core.config import Settings
from web_access.core.ids import IdGenerator
from web_access.core.time import Clock


class RestDependencies(Protocol):
    settings: Settings
    clock: Clock
    ids: IdGenerator
    auth: AuthProvider
    health: HealthService
    metrics: Metrics
    search: SearchApplicationService
    search_readiness: SearchProviderReadinessService


def dependencies_from_request(request: Request) -> RestDependencies:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("runtime dependencies are unavailable")
    return cast(RestDependencies, container)
