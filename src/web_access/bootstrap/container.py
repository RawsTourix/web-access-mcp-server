"""Typed composition data owned exclusively by bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy.ext.asyncio import AsyncEngine

from web_access.application.common.health import HealthService
from web_access.core.config import Settings
from web_access.core.ids import IdGenerator
from web_access.core.time import Clock
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.infrastructure.content.filesystem import FilesystemContentStore
from web_access.infrastructure.database.uow import SqlAlchemyUnitOfWorkFactory
from web_access.infrastructure.observability.metrics import ServiceMetrics
from web_access.infrastructure.redis.client import RedisDependency


@dataclass(frozen=True, slots=True)
class RuntimeContainer:
    settings: Settings
    clock: Clock
    ids: IdGenerator
    auth: StaticBearerAuthProvider
    database_engine: AsyncEngine
    uow_factory: SqlAlchemyUnitOfWorkFactory
    redis: RedisDependency
    content_store: FilesystemContentStore
    health: HealthService
    metrics: ServiceMetrics
    tracer_provider: TracerProvider | None
