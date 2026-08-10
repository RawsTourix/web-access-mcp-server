"""Deterministic Search provider resolution and capability validation."""

from __future__ import annotations

from web_access.application.search.models import ProviderDescriptor, SearchQuery
from web_access.application.search.ports import SearchProvider
from web_access.domain.search import SearchProviderId, SearchProviderSelection


class ProviderResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SearchProviderRegistry:
    def __init__(
        self,
        providers: tuple[SearchProvider, ...],
        *,
        default_provider: SearchProviderId,
    ) -> None:
        by_id = {provider.descriptor.provider_id: provider for provider in providers}
        if len(by_id) != len(providers):
            raise ValueError("duplicate Search provider")
        if default_provider not in by_id:
            raise ValueError("default Search provider is not configured")
        if not by_id[default_provider].descriptor.enabled:
            raise ValueError("default Search provider is disabled")
        self._providers = by_id
        self._default = default_provider

    @property
    def default_provider_id(self) -> SearchProviderId:
        return self._default

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(provider.descriptor for provider in self._providers.values())

    def resolve(self, selection: SearchProviderSelection) -> SearchProvider:
        provider_id = (
            self._default
            if selection is SearchProviderSelection.DEFAULT
            else SearchProviderId(selection)
        )
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderResolutionError("unknown_provider", "Search provider is not configured.")
        if not provider.descriptor.enabled:
            raise ProviderResolutionError("provider_disabled", "Search provider is disabled.")
        return provider

    @staticmethod
    def validate_capabilities(provider: SearchProvider, query: SearchQuery) -> None:
        capabilities = provider.descriptor.capabilities
        unsupported: list[str] = []
        if query.page > 1 and not capabilities.pagination:
            unsupported.append("page")
        if query.language is not None and not capabilities.language:
            unsupported.append("language")
        if query.region is not None and not capabilities.region:
            unsupported.append("region")
        if query.safe_search is not None and not capabilities.safe_search:
            unsupported.append("safe_search")
        if query.time_range is not None and not capabilities.time_range:
            unsupported.append("time_range")
        if query.limit > capabilities.max_results:
            unsupported.append("limit")
        if unsupported:
            raise ProviderResolutionError(
                "unsupported_option", f"Provider does not support: {', '.join(unsupported)}"
            )
