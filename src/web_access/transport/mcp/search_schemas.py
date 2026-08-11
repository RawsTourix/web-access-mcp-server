"""Exact compact MCP `web_search` input schema."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.search.models import SearchBatchRequest, SearchQuery
from web_access.domain.search import (
    SearchLanguage,
    SearchProviderSelection,
    SearchRegionId,
    SearchSafeMode,
    SearchTimeRange,
)

McpQueryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
]
McpOption = Annotated[str, StringConstraints(min_length=1, max_length=64)]


def _language(value: str) -> str:
    return str(SearchLanguage.parse(value))


def _region(value: str) -> str:
    return str(SearchRegionId(value))


McpQueries = Annotated[
    tuple[McpQueryText, ...],
    Field(
        min_length=1,
        max_length=8,
        description="От одного до восьми независимых поисковых запросов.",
    ),
]
McpProvider = Annotated[
    SearchProviderSelection,
    Field(
        description=(
            "`default` использует настроенный default provider; `searxng` использует "
            "бесплатный configured SearXNG backend; `yandex` может расходовать платный "
            "provider budget. Сервис не переключает provider скрыто из-за размера, "
            "качества выдачи или ошибки."
        )
    ),
]
McpPage = Annotated[int, Field(ge=1, le=100, description="Страница поисковой выдачи.")]
McpLimit = Annotated[
    int, Field(ge=1, le=20, description="Максимальное число результатов на запрос.")
]
McpLanguage = Annotated[
    Annotated[McpOption, AfterValidator(_language)] | MISSING,
    Field(description="Нормализуемый BCP 47 language tag; поле можно опустить."),
]
McpRegion = Annotated[
    Annotated[McpOption, AfterValidator(_region)] | MISSING,
    Field(description="Канонический публичный Search region ID; поле можно опустить."),
]
McpSafeSearch = Annotated[
    SearchSafeMode | MISSING,
    Field(description="Режим safe search; поле можно опустить."),
]
McpTimeRange = Annotated[
    SearchTimeRange | MISSING,
    Field(description="Ограничение периода поиска; поле можно опустить."),
]


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: McpQueries
    provider: McpProvider = SearchProviderSelection.DEFAULT
    page: McpPage = 1
    limit: McpLimit = 10
    language: McpLanguage = MISSING
    region: McpRegion = MISSING
    safe_search: McpSafeSearch = MISSING
    time_range: McpTimeRange = MISSING

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
