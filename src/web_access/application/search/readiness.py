"""Independent Search provider discovery and readiness aggregation."""

from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from web_access.application.common.health import Availability
from web_access.application.search.ports import SearchTelemetry
from web_access.application.search.registry import SearchProviderRegistry
from web_access.domain.search import SearchProviderId


class PublicProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pagination: bool
    language: bool
    region: bool
    safe_search: bool
    time_range: bool


class SearchProviderDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: SearchProviderId
    name: str
    enabled: bool
    billable: bool
    capabilities: PublicProviderCapabilities
    readiness: Availability


class ProviderReadinessProbe(Protocol):
    @property
    def provider_id(self) -> SearchProviderId: ...

    async def check(self) -> Availability: ...


class SearchProviderReadinessService:
    def __init__(
        self,
        *,
        providers: SearchProviderRegistry,
        probes: tuple[ProviderReadinessProbe, ...],
        telemetry: SearchTelemetry,
    ) -> None:
        by_id = {probe.provider_id: probe for probe in probes}
        if len(by_id) != len(probes):
            raise ValueError("duplicate Search provider readiness probe")
        self._providers = providers
        self._probes = by_id
        self._telemetry = telemetry

    async def providers(self) -> tuple[SearchProviderDiscovery, ...]:
        descriptors = self._providers.descriptors()

        async def readiness(provider_id: SearchProviderId, enabled: bool) -> Availability:
            probe = self._probes.get(provider_id)
            if not enabled or probe is None:
                return Availability.UNAVAILABLE
            try:
                return await probe.check()
            except Exception:
                return Availability.UNAVAILABLE

        states = await asyncio.gather(
            *(readiness(item.provider_id, item.enabled) for item in descriptors)
        )
        result: list[SearchProviderDiscovery] = []
        for descriptor, state in zip(descriptors, states, strict=True):
            capabilities = descriptor.capabilities
            result.append(
                SearchProviderDiscovery(
                    provider_id=descriptor.provider_id,
                    name=descriptor.name,
                    enabled=descriptor.enabled,
                    billable=descriptor.billable,
                    capabilities=PublicProviderCapabilities(
                        pagination=capabilities.pagination,
                        language=capabilities.language,
                        region=capabilities.region,
                        safe_search=capabilities.safe_search,
                        time_range=capabilities.time_range,
                    ),
                    readiness=state,
                )
            )
            self._telemetry.observe_provider_readiness(descriptor.provider_id, state.value)
        return tuple(result)
