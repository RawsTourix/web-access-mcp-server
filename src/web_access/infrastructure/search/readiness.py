"""Non-billable provider readiness probes with mandatory dependency semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from web_access.application.common.health import Availability
from web_access.core.config import SearxngSettings, YandexSearchSettings
from web_access.domain.search import SearchProviderId

DependencyProbe = Callable[[], Awaitable[bool]]


class SearxngProviderReadinessProbe:
    provider_id = SearchProviderId.SEARXNG

    def __init__(
        self,
        *,
        settings: SearxngSettings,
        client: httpx.AsyncClient,
        rate_dependency: DependencyProbe,
    ) -> None:
        self._settings = settings
        self._client = client
        self._rate_dependency = rate_dependency

    async def check(self) -> Availability:
        if not self._settings.enabled or not await self._rate_dependency():
            return Availability.UNAVAILABLE
        try:
            async with self._client.stream(
                "GET",
                str(self._settings.endpoint).rstrip("/") + "/healthz",
                timeout=httpx.Timeout(min(2.0, self._settings.request_timeout_seconds)),
            ) as response:
                if response.status_code != 200:
                    return Availability.UNAVAILABLE
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1024:
                        return Availability.UNAVAILABLE
        except httpx.HTTPError:
            return Availability.UNAVAILABLE
        return Availability.READY


class YandexProviderReadinessProbe:
    """Dependency/config readiness only; never spends a Search request."""

    provider_id = SearchProviderId.YANDEX

    def __init__(
        self,
        *,
        settings: YandexSearchSettings,
        rate_dependency: DependencyProbe,
        usage_database: DependencyProbe,
    ) -> None:
        self._settings = settings
        self._rate_dependency = rate_dependency
        self._usage_database = usage_database

    async def check(self) -> Availability:
        if not self._settings.enabled:
            return Availability.UNAVAILABLE
        if self._settings.folder_id is None or self._settings.api_key is None:
            return Availability.UNAVAILABLE
        rate_ready, usage_ready = await asyncio.gather(
            self._rate_dependency(), self._usage_database()
        )
        return Availability.READY if rate_ready and usage_ready else Availability.UNAVAILABLE
