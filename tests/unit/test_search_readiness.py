"""S11 independent and non-billable provider readiness semantics."""

from __future__ import annotations

import httpx
import pytest

from web_access.application.common.context import ExecutionContext
from web_access.application.common.health import Availability
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
)
from web_access.application.search.readiness import SearchProviderReadinessService
from web_access.application.search.registry import SearchProviderRegistry
from web_access.core.config import SearxngSettings, YandexSearchSettings
from web_access.domain.search import SearchProviderId
from web_access.infrastructure.observability import SearchTelemetryAdapter, create_metrics
from web_access.infrastructure.search.readiness import (
    SearxngProviderReadinessProbe,
    YandexProviderReadinessProbe,
)


class DiscoveryProvider:
    def __init__(self, provider_id: SearchProviderId, *, enabled: bool = True) -> None:
        self.descriptor = ProviderDescriptor(
            provider_id=provider_id,
            name=provider_id.value,
            enabled=enabled,
            configuration_revision=f"readiness-{provider_id.value}",
            capabilities=ProviderCapabilities(
                pagination=True,
                language=provider_id is SearchProviderId.SEARXNG,
                region=provider_id is SearchProviderId.YANDEX,
                safe_search=True,
                time_range=True,
                max_results=50,
                billable=provider_id is SearchProviderId.YANDEX,
            ),
        )

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = context, request
        raise NotImplementedError


class FixedProbe:
    def __init__(self, provider_id: SearchProviderId, state: Availability) -> None:
        self.provider_id = provider_id
        self.state = state
        self.calls = 0

    async def check(self) -> Availability:
        self.calls += 1
        return self.state


async def _true() -> bool:
    return True


async def _false() -> bool:
    return False


@pytest.mark.asyncio
async def test_optional_yandex_outage_does_not_disable_ready_searxng() -> None:
    searxng = DiscoveryProvider(SearchProviderId.SEARXNG)
    yandex = DiscoveryProvider(SearchProviderId.YANDEX)
    providers = SearchProviderRegistry(
        (searxng, yandex),
        default_provider=SearchProviderId.SEARXNG,
    )
    metrics = create_metrics()
    service = SearchProviderReadinessService(
        providers=providers,
        probes=(
            FixedProbe(SearchProviderId.SEARXNG, Availability.READY),
            FixedProbe(SearchProviderId.YANDEX, Availability.UNAVAILABLE),
        ),
        telemetry=SearchTelemetryAdapter(metrics),
    )
    result = await service.providers()
    assert [(item.provider_id, item.readiness) for item in result] == [
        (SearchProviderId.SEARXNG, Availability.READY),
        (SearchProviderId.YANDEX, Availability.UNAVAILABLE),
    ]
    assert result[0].capabilities.language is True
    assert result[1].billable is True
    rendered = metrics.render().decode()
    assert 'provider="searxng",status="ready"' in rendered
    assert 'provider="yandex",status="unavailable"' in rendered


@pytest.mark.asyncio
async def test_searxng_probe_uses_only_private_non_billable_health_protocol() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"OK")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = SearxngProviderReadinessProbe(
            settings=SearxngSettings.model_validate({"endpoint": "http://searxng:8080"}),
            client=client,
            rate_dependency=_true,
        )
        assert await probe.check() is Availability.READY
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert calls[0].url.path == "/healthz"
    assert "q" not in calls[0].url.params


@pytest.mark.asyncio
async def test_redis_failure_makes_searxng_unavailable_without_http_call() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        probe = SearxngProviderReadinessProbe(
            settings=SearxngSettings.model_validate({"endpoint": "http://searxng:8080"}),
            client=client,
            rate_dependency=_false,
        )
        assert await probe.check() is Availability.UNAVAILABLE
    assert calls == 0


@pytest.mark.parametrize(
    ("rate_ready", "database_ready", "expected"),
    [
        (True, True, Availability.READY),
        (False, True, Availability.UNAVAILABLE),
        (True, False, Availability.UNAVAILABLE),
    ],
)
@pytest.mark.asyncio
async def test_yandex_readiness_uses_config_redis_and_postgres_without_search(
    rate_ready: bool, database_ready: bool, expected: Availability
) -> None:
    calls = {"rate": 0, "database": 0}

    async def rate() -> bool:
        calls["rate"] += 1
        return rate_ready

    async def database() -> bool:
        calls["database"] += 1
        return database_ready

    probe = YandexProviderReadinessProbe(
        settings=YandexSearchSettings.model_validate(
            {"enabled": True, "folder_id": "folder", "api_key": "secret-api-key"}
        ),
        rate_dependency=rate,
        usage_database=database,
    )
    assert await probe.check() is expected
    assert calls == {"rate": 1, "database": 1}


@pytest.mark.asyncio
async def test_disabled_provider_is_unavailable_without_invoking_probe() -> None:
    enabled = DiscoveryProvider(SearchProviderId.SEARXNG)
    disabled = DiscoveryProvider(SearchProviderId.YANDEX, enabled=False)
    providers = SearchProviderRegistry(
        (enabled, disabled),
        default_provider=SearchProviderId.SEARXNG,
    )
    disabled_probe = FixedProbe(SearchProviderId.YANDEX, Availability.READY)
    service = SearchProviderReadinessService(
        providers=providers,
        probes=(
            FixedProbe(SearchProviderId.SEARXNG, Availability.READY),
            disabled_probe,
        ),
        telemetry=SearchTelemetryAdapter(create_metrics()),
    )
    result = await service.providers()
    assert result[1].readiness is Availability.UNAVAILABLE
    assert disabled_probe.calls == 0
