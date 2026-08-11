"""Search application contracts and orchestration."""

from web_access.application.search.models import (
    CacheMetadata,
    PaginationMetadata,
    ProviderCapabilities,
    ProviderDescriptor,
    SearchBatchRequest,
    SearchBatchResult,
    SearchQuery,
    SearchQueryData,
    SearchRegionEntry,
    SearchRegionMapping,
    SearchUsageMetadata,
)
from web_access.application.search.registry import SearchProviderRegistry, SearchRegionRegistry
from web_access.application.search.service import SearchApplicationService, SearchServicePolicy

__all__ = [
    "CacheMetadata",
    "PaginationMetadata",
    "ProviderCapabilities",
    "ProviderDescriptor",
    "SearchApplicationService",
    "SearchBatchRequest",
    "SearchBatchResult",
    "SearchProviderRegistry",
    "SearchQuery",
    "SearchQueryData",
    "SearchRegionEntry",
    "SearchRegionMapping",
    "SearchRegionRegistry",
    "SearchServicePolicy",
    "SearchUsageMetadata",
]
from web_access.application.search.readiness import (
    PublicProviderCapabilities,
    SearchProviderDiscovery,
    SearchProviderReadinessService,
)

__all__ = [
    "PublicProviderCapabilities",
    "SearchProviderDiscovery",
    "SearchProviderReadinessService",
]
