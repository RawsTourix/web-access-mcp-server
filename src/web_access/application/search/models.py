"""Typed Search requests, results, provider metadata, and attempt evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from web_access.application.common.hints import Warning
from web_access.application.common.results import BatchItemResult
from web_access.domain.search import (
    SearchLanguage,
    SearchProviderId,
    SearchProviderSelection,
    SearchRegionId,
    SearchResultItem,
    SearchSafeMode,
    SearchTimeRange,
)

SearchQueryText = Annotated[str, Field(min_length=1, max_length=4096)]


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    web_search: bool = True
    pagination: bool
    language: bool
    region: bool
    safe_search: bool
    time_range: bool
    max_results: int = Field(ge=1, le=50)
    max_query_length: int = Field(default=4096, ge=1, le=4096)
    supported_time_ranges: tuple[SearchTimeRange, ...] = (
        SearchTimeRange.DAY,
        SearchTimeRange.MONTH,
        SearchTimeRange.YEAR,
    )
    billable: bool

    @model_validator(mode="after")
    def validate_time_range_capability(self) -> ProviderCapabilities:
        if self.time_range and not self.supported_time_ranges:
            raise ValueError("time range capability requires at least one supported value")
        if not self.time_range and self.supported_time_ranges:
            raise ValueError("unsupported time range capability cannot declare supported values")
        if len(self.supported_time_ranges) != len(set(self.supported_time_ranges)):
            raise ValueError("duplicate supported time range")
        return self


class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: SearchProviderId
    name: str = Field(min_length=1, max_length=128)
    enabled: bool
    capabilities: ProviderCapabilities
    configuration_revision: str = Field(min_length=8, max_length=128)

    @property
    def billable(self) -> bool:
        return self.capabilities.billable


class SearchRegionMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: SearchProviderId
    provider_region: str = Field(min_length=1, max_length=128)


class SearchRegionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    region_id: SearchRegionId
    label: str = Field(min_length=1, max_length=128)
    mappings: tuple[SearchRegionMapping, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def unique_provider_mappings(self) -> SearchRegionEntry:
        provider_ids = [mapping.provider_id for mapping in self.mappings]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("duplicate provider mapping for Search region")
        return self


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    query: SearchQueryText
    provider: SearchProviderSelection = SearchProviderSelection.DEFAULT
    page: int = Field(default=1, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=50)
    language: SearchLanguage | None = None
    region: SearchRegionId | None = None
    safe_search: SearchSafeMode | None = None
    time_range: SearchTimeRange | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            if isinstance(value.get("query"), str):
                value["query"] = value["query"].strip()
            if isinstance(value.get("language"), str):
                value["language"] = SearchLanguage.parse(value["language"])
            if isinstance(value.get("region"), str):
                value["region"] = SearchRegionId(value["region"])
        return value


class SearchBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: tuple[SearchQuery, ...] = Field(min_length=1, max_length=32)


class CacheMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cached: bool
    retrieved_at: datetime


class PaginationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1, le=100)
    next_page_available: bool | None = None


class SearchUsageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    upstream_attempts: int = Field(default=0, ge=0, le=16)
    rate_units: int = Field(default=0, ge=0, le=16)
    billable_attempts: int = Field(default=0, ge=0, le=16)
    internal_retries: int = Field(default=0, ge=0, le=15)


class SearchQueryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    query: str = Field(min_length=1, max_length=4096)
    provider_id: SearchProviderId
    page: int = Field(ge=1, le=100)
    requested_limit: int = Field(ge=1, le=50)
    results: tuple[SearchResultItem, ...] = Field(max_length=50)
    cache: CacheMetadata
    pagination: PaginationMetadata
    usage: SearchUsageMetadata = Field(default_factory=SearchUsageMetadata)


class SearchBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[BatchItemResult[SearchQueryData], ...] = Field(min_length=1, max_length=32)


class ProviderSearchRequest(BaseModel):
    """One normalized request to one concrete provider attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    query: str = Field(min_length=1, max_length=4096)
    provider_id: SearchProviderId
    page: int = Field(ge=1, le=100)
    limit: int = Field(ge=1, le=50)
    language: SearchLanguage | None = None
    region: SearchRegionId | None = None
    provider_region: str | None = Field(default=None, min_length=1, max_length=128)
    safe_search: SearchSafeMode | None = None
    time_range: SearchTimeRange | None = None


class ProviderSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    provider_id: SearchProviderId
    results: tuple[SearchResultItem, ...] = Field(max_length=50)
    retrieved_at: datetime
    next_page_available: bool | None = None
    provider_request_id: str | None = Field(default=None, max_length=256)
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
