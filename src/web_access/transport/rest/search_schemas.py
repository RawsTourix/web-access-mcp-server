"""Exact v0.2 REST Search input and output schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.search.language import normalize_search_language
from web_access.application.search.models import SearchBatchRequest, SearchQuery
from web_access.domain.search import (
    SearchProviderSelection,
    SearchRegionId,
    SearchSafeMode,
    SearchTimeRange,
)

RestQueryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
BoundedOption = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class RestSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: RestQueryText
    provider: SearchProviderSelection = SearchProviderSelection.DEFAULT
    page: int = Field(default=1, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=50)
    language: BoundedOption | MISSING = MISSING
    region: BoundedOption | MISSING = MISSING
    safe_search: SearchSafeMode | MISSING = MISSING
    time_range: SearchTimeRange | MISSING = MISSING

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | MISSING) -> str | MISSING:
        if value is MISSING:
            return value
        return str(normalize_search_language(value))

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str | MISSING) -> str | MISSING:
        if value is MISSING:
            return value
        return str(SearchRegionId(value))

    def to_application(self) -> SearchQuery:
        payload: dict[str, object] = {
            "query": self.query,
            "provider": self.provider,
            "page": self.page,
            "limit": self.limit,
        }
        for field in ("language", "region", "safe_search", "time_range"):
            value = getattr(self, field)
            if value is not MISSING:
                payload[field] = value
        return SearchQuery.model_validate(payload)


class RestSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: tuple[RestSearchQuery, ...] = Field(min_length=1, max_length=32)

    def to_application(self) -> SearchBatchRequest:
        return SearchBatchRequest(queries=tuple(item.to_application() for item in self.queries))
