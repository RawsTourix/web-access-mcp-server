"""Typed composition data owned exclusively by bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy.ext.asyncio import AsyncEngine

from web_access.application.common.auth import AuthProvider
from web_access.application.common.health import HealthService
from web_access.application.common.observability import Metrics
from web_access.application.content.service import ContentApplicationService
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.application.search.readiness import SearchProviderReadinessService
from web_access.application.search.service import SearchApplicationService
from web_access.core.config import Settings
from web_access.core.ids import IdGenerator
from web_access.core.time import Clock
from web_access.infrastructure.content.filesystem import FilesystemContentStore
from web_access.infrastructure.database.uow import SqlAlchemyUnitOfWorkFactory
from web_access.infrastructure.redis.client import RedisDependency


@dataclass(frozen=True, slots=True)
class RuntimeContainer:
    settings: Settings
    clock: Clock
    ids: IdGenerator
    auth: AuthProvider
    database_engine: AsyncEngine
    uow_factory: SqlAlchemyUnitOfWorkFactory
    redis: RedisDependency
    content_store: FilesystemContentStore
    health: HealthService
    metrics: Metrics
    tracer_provider: TracerProvider | None
    search: SearchApplicationService
    search_readiness: SearchProviderReadinessService
    content: ContentApplicationService
    retrieval: RetrievalApplicationService
