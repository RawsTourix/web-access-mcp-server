"""Deterministic creation and reverse-order shutdown of foundation dependencies."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from opentelemetry.sdk.trace import TracerProvider

from web_access.application.common.health import DependencyProbe, HealthService
from web_access.application.search.models import SearchRegionEntry, SearchRegionMapping
from web_access.application.search.readiness import SearchProviderReadinessService
from web_access.application.search.registry import SearchProviderRegistry, SearchRegionRegistry
from web_access.application.search.service import SearchApplicationService, SearchServicePolicy
from web_access.bootstrap.container import RuntimeContainer
from web_access.core.config import Settings
from web_access.core.ids import Uuid4IdGenerator
from web_access.core.time import SystemClock
from web_access.domain.search import SearchProviderId, SearchRegionId
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
from web_access.infrastructure.observability.search import (
    ObservedSearchProvider,
    SearchTelemetryAdapter,
)
from web_access.infrastructure.observability.tracing import configure_tracing, shutdown_tracing
from web_access.infrastructure.redis.client import RedisDependency
from web_access.infrastructure.search import (
    ProviderConcurrencyPolicy,
    ProviderRatePolicy,
    RedisProviderConcurrencyLimiter,
    RedisProviderFlowControlReadiness,
    RedisProviderRateLimiter,
    RedisSearchCache,
    RedisSearchSingleFlight,
    SearxngProviderReadinessProbe,
    SearxngSearchProvider,
    SqlAlchemySearchUsageUnitOfWorkFactory,
    TokenBucketPolicy,
    YandexProviderReadinessProbe,
    YandexSearchProvider,
)


@asynccontextmanager
async def runtime_lifespan(
    settings: Settings,
    auth_provider: StaticBearerAuthProvider | None = None,
    tracer_provider: TracerProvider | None = None,
) -> AsyncIterator[RuntimeContainer]:
    """Build concrete dependencies on entry and release ownership in reverse order."""

    configure_logging(settings.observability)
    logger = structlog.get_logger(__name__)
    logger.info("runtime_starting", config=settings.safe_summary())
    clock = SystemClock()
    ids = Uuid4IdGenerator()
    metrics = create_metrics()
    selected_tracer_provider = tracer_provider or configure_tracing(
        settings.observability, settings.app.service_name
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
    searxng_http = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.search.concurrency.searxng.local_limit,
            max_keepalive_connections=settings.search.concurrency.searxng.local_limit,
        ),
        follow_redirects=False,
    )
    yandex_http = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.search.concurrency.yandex.local_limit,
            max_keepalive_connections=settings.search.concurrency.yandex.local_limit,
        ),
        follow_redirects=False,
    )
    try:
        await content_store.start()
        await redis.start()
        telemetry = SearchTelemetryAdapter(metrics)
        concrete_providers = (
            ObservedSearchProvider(
                SearxngSearchProvider(settings.search.searxng, searxng_http),
                metrics=metrics,
                tracer_provider=selected_tracer_provider,
            ),
            ObservedSearchProvider(
                YandexSearchProvider(settings.search.yandex, yandex_http),
                metrics=metrics,
                tracer_provider=selected_tracer_provider,
            ),
        )
        provider_registry = SearchProviderRegistry(
            concrete_providers,
            default_provider=SearchProviderId(settings.search.default_provider),
        )
        regions = SearchRegionRegistry(
            tuple(
                SearchRegionEntry(
                    region_id=SearchRegionId(region.region_id),
                    label=region.label,
                    mappings=tuple(
                        SearchRegionMapping(
                            provider_id=SearchProviderId(mapping.provider_id),
                            provider_region=mapping.provider_region,
                        )
                        for mapping in region.mappings
                    ),
                )
                for region in settings.search.regions
            )
        )
        rate_limiter = RedisProviderRateLimiter(
            redis.client,
            namespace=settings.redis.namespace,
            policies={
                provider_id: _rate_policy(settings, provider_id) for provider_id in SearchProviderId
            },
            state_loss_horizons=_flow_control_horizons(settings),
        )
        concurrency_limiter = RedisProviderConcurrencyLimiter(
            redis.client,
            namespace=settings.redis.namespace,
            policies={
                provider_id: _concurrency_policy(settings, provider_id)
                for provider_id in SearchProviderId
            },
            state_loss_horizons=_flow_control_horizons(settings),
        )
        flow_readiness = RedisProviderFlowControlReadiness(
            redis.client, namespace=settings.redis.namespace
        )
        search = SearchApplicationService(
            providers=provider_registry,
            regions=regions,
            cache=RedisSearchCache(redis.client, namespace=settings.redis.namespace),
            single_flight=RedisSearchSingleFlight(
                redis.client,
                namespace=settings.redis.namespace,
                lease_seconds=settings.search.cache.single_flight_ttl_seconds,
                poll_seconds=settings.search.cache.waiter_poll_seconds,
            ),
            rate_limiter=rate_limiter,
            concurrency_limiter=concurrency_limiter,
            usage_uow_factory=SqlAlchemySearchUsageUnitOfWorkFactory(session_factory),
            telemetry=telemetry,
            policy=SearchServicePolicy(
                cache_mode=settings.search.cache.mode,
                searxng_cache_ttl_seconds=settings.search.cache.searxng_ttl_seconds,
                yandex_cache_ttl_seconds=settings.search.cache.yandex_ttl_seconds,
                searxng_max_attempts=settings.search.retry.searxng_max_attempts,
                yandex_max_attempts=settings.search.retry.yandex_max_attempts,
                batch_concurrency=settings.search.batch_concurrency,
                operation_timeout_seconds=settings.search.operation_timeout_seconds,
                retry_backoff_seconds=settings.search.retry.backoff_seconds,
                retry_jitter_ratio=settings.search.retry.jitter_ratio,
            ),
        )
        search_readiness = SearchProviderReadinessService(
            providers=provider_registry,
            probes=(
                SearxngProviderReadinessProbe(
                    settings=settings.search.searxng,
                    client=searxng_http,
                    admission_dependency=lambda: flow_readiness.check(SearchProviderId.SEARXNG),
                ),
                YandexProviderReadinessProbe(
                    settings=settings.search.yandex,
                    admission_dependency=lambda: flow_readiness.check(SearchProviderId.YANDEX),
                    usage_database=lambda: probe_database(engine),
                ),
            ),
            telemetry=telemetry,
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
            tracer_provider=selected_tracer_provider,
            search=search,
            search_readiness=search_readiness,
        )
        health.mark_bootstrapped()
        logger.info("runtime_started")
        yield container
    finally:
        health.begin_shutdown()
        try:
            async with asyncio.timeout(settings.security.shutdown_timeout_seconds):
                for dependency, close in (
                    ("yandex_http", yandex_http.aclose),
                    ("searxng_http", searxng_http.aclose),
                    ("redis", redis.close),
                    ("database", lambda: close_engine(engine)),
                    (
                        "tracing",
                        lambda: asyncio.to_thread(shutdown_tracing, selected_tracer_provider),
                    ),
                ):
                    try:
                        await close()
                    except Exception:
                        logger.error("runtime_dependency_shutdown_failed", dependency=dependency)
        except TimeoutError:
            logger.error(
                "runtime_shutdown_timed_out",
                timeout_seconds=settings.security.shutdown_timeout_seconds,
            )
        logger.info("runtime_stopped")


def _rate_policy(settings: Settings, provider_id: SearchProviderId) -> ProviderRatePolicy:
    configured = (
        settings.search.rate_limit.searxng
        if provider_id is SearchProviderId.SEARXNG
        else settings.search.rate_limit.yandex
    )
    return ProviderRatePolicy(
        principal=TokenBucketPolicy(
            configured.principal.capacity, configured.principal.refill_per_second
        ),
        global_=TokenBucketPolicy(
            configured.global_.capacity, configured.global_.refill_per_second
        ),
    )


def _concurrency_policy(
    settings: Settings, provider_id: SearchProviderId
) -> ProviderConcurrencyPolicy:
    configured = (
        settings.search.concurrency.searxng
        if provider_id is SearchProviderId.SEARXNG
        else settings.search.concurrency.yandex
    )
    return ProviderConcurrencyPolicy(
        local_limit=configured.local_limit,
        global_limit=configured.global_limit,
        lease_seconds=configured.lease_seconds,
        admission_timeout_seconds=configured.admission_timeout_seconds,
    )


def _flow_control_horizons(settings: Settings) -> dict[SearchProviderId, float]:
    result: dict[SearchProviderId, float] = {}
    for provider_id in SearchProviderId:
        rate = _rate_policy(settings, provider_id)
        concurrency = _concurrency_policy(settings, provider_id)
        result[provider_id] = max(
            rate.principal.capacity / rate.principal.refill_per_second,
            rate.global_.capacity / rate.global_.refill_per_second,
            concurrency.lease_seconds,
        )
    return result
