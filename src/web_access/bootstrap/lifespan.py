"""Deterministic creation and reverse-order shutdown of foundation dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog

from web_access.application.common.health import DependencyProbe, HealthService
from web_access.bootstrap.container import RuntimeContainer
from web_access.core.config import Settings
from web_access.core.ids import Uuid4IdGenerator
from web_access.core.time import SystemClock
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.infrastructure.content.filesystem import FilesystemContentStore
from web_access.infrastructure.database.engine import (
    close_engine,
    create_engine,
    create_session_factory,
    probe_database,
)
from web_access.infrastructure.database.uow import SqlAlchemyUnitOfWorkFactory
from web_access.infrastructure.observability.logging import configure_logging
from web_access.infrastructure.observability.metrics import create_metrics
from web_access.infrastructure.observability.tracing import configure_tracing, shutdown_tracing
from web_access.infrastructure.redis.client import RedisDependency


@asynccontextmanager
async def runtime_lifespan(
    settings: Settings,
    auth_provider: StaticBearerAuthProvider | None = None,
) -> AsyncIterator[RuntimeContainer]:
    """Build concrete dependencies on entry and release ownership in reverse order."""

    configure_logging(settings.observability)
    logger = structlog.get_logger(__name__)
    logger.info("runtime_starting", config=settings.safe_summary())
    clock = SystemClock()
    ids = Uuid4IdGenerator()
    metrics = create_metrics()
    tracer_provider = configure_tracing(
        settings.observability,
        settings.app.service_name,
    )
    engine = create_engine(settings.database)
    session_factory = create_session_factory(engine)
    redis = RedisDependency(settings.redis)
    content_store = FilesystemContentStore(settings.content_store)
    auth = auth_provider or StaticBearerAuthProvider(settings.auth.principals)
    health = HealthService(
        clock=clock,
        probes=(
            DependencyProbe(
                "postgres",
                "postgres" in settings.app.mandatory_dependencies,
                lambda: probe_database(engine),
            ),
            DependencyProbe(
                "redis",
                "redis" in settings.app.mandatory_dependencies,
                redis.ping,
            ),
            DependencyProbe(
                "content_store",
                "content_store" in settings.app.mandatory_dependencies,
                content_store.probe,
            ),
        ),
    )
    container = RuntimeContainer(
        settings=settings,
        clock=clock,
        ids=ids,
        auth=auth,
        database_engine=engine,
        uow_factory=SqlAlchemyUnitOfWorkFactory(session_factory),
        redis=redis,
        content_store=content_store,
        health=health,
        metrics=metrics,
        tracer_provider=tracer_provider,
    )
    try:
        await content_store.start()
        await redis.start()
        health.mark_bootstrapped()
        logger.info("runtime_started")
        yield container
    finally:
        health.begin_shutdown()
        await redis.close()
        await close_engine(engine)
        shutdown_tracing(tracer_provider)
        logger.info("runtime_stopped")
