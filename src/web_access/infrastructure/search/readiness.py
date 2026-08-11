"""Non-billable provider readiness probes with mandatory dependency semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from web_access.application.common.health import Availability
from web_access.core.config import SearxngSettings, YandexSearchSettings
from web_access.domain.search import SearchProviderId

DependencyProbe = Callable[[], Awaitable[bool]]
AdmissionProbe = Callable[[], Awaitable[Availability]]


class SearxngProviderReadinessProbe:
    provider_id = SearchProviderId.SEARXNG

    def __init__(
        self,
        *,
        settings: SearxngSettings,
        client: httpx.AsyncClient,
        admission_dependency: AdmissionProbe,
    ) -> None:
        self._settings = settings
        self._client = client
        self._admission_dependency = admission_dependency

    async def check(self) -> Availability:
        if (
            not self._settings.enabled
            or await self._admission_dependency() is not Availability.READY
        ):
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
        admission_dependency: AdmissionProbe,
        usage_database: DependencyProbe,
    ) -> None:
        self._settings = settings
        self._admission_dependency = admission_dependency
        self._usage_database = usage_database

    async def check(self) -> Availability:
        if not self._settings.enabled:
            return Availability.UNAVAILABLE
        if self._settings.folder_id is None or self._settings.api_key is None:
            return Availability.UNAVAILABLE
        admission, usage_ready = await asyncio.gather(
            self._admission_dependency(), self._usage_database()
        )
        return (
            Availability.READY
            if admission is Availability.READY and usage_ready
            else Availability.UNAVAILABLE
        )
