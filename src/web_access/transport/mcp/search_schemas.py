"""Exact compact MCP `web_search` input schema."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.search.models import SearchBatchRequest, SearchQuery
from web_access.domain.search import SearchProviderSelection, SearchSafeMode, SearchTimeRange

McpQueryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
]
McpOption = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: tuple[McpQueryText, ...] = Field(min_length=1, max_length=8)
    provider: SearchProviderSelection = SearchProviderSelection.DEFAULT
    page: int = Field(default=1, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=20)
    language: McpOption | MISSING = MISSING
    region: McpOption | MISSING = MISSING
    safe_search: SearchSafeMode | MISSING = MISSING
    time_range: SearchTimeRange | MISSING = MISSING

    def to_application(self) -> SearchBatchRequest:
        common: dict[str, object] = {
            "provider": self.provider,
            "page": self.page,
            "limit": self.limit,
        }
        for field in ("language", "region", "safe_search", "time_range"):
            value = getattr(self, field)
            if value is not MISSING:
                common[field] = value
        return SearchBatchRequest(
            queries=tuple(
                SearchQuery.model_validate({"query": query, **common}) for query in self.queries
            )
        )
