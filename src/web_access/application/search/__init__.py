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
    SearchUsageMetadata,
)
from web_access.application.search.registry import SearchProviderRegistry

__all__ = [
    "CacheMetadata",
    "PaginationMetadata",
    "ProviderCapabilities",
    "ProviderDescriptor",
    "SearchBatchRequest",
    "SearchBatchResult",
    "SearchProviderRegistry",
    "SearchQuery",
    "SearchQueryData",
    "SearchUsageMetadata",
]
