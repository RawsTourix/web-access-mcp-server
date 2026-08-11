"""Strict compact MCP schemas for Retrieval and Content tools."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.common.results import BatchItemResult
from web_access.application.content.models import ContentReadResult
from web_access.domain.retrieval import RetrievalBatchRequest, RetrievalRequestItem


def _http_url(value: str) -> str:
    RetrievalRequestItem(value)
    return value


McpHttpUrl = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4096),
    AfterValidator(_http_url),
]
McpUrls = Annotated[
    tuple[McpHttpUrl, ...],
    Field(
        min_length=1,
        max_length=8,
        description=(
            "От одного до восьми известных HTTP(S)-URL. Порядок и повторяющиеся позиции "
            "сохраняются."
        ),
    ),
]
McpContentId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128),
    Field(description="Непрозрачный идентификатор существующего ContentObject."),
]
McpCursor = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2048),
    Field(description="Opaque cursor из предыдущего результата `content_get`."),
]


class WebFetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    urls: McpUrls

    def to_application(self) -> RetrievalBatchRequest:
        return RetrievalBatchRequest(tuple(RetrievalRequestItem(url) for url in self.urls))


class ContentReadItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_id: McpContentId
    cursor: Annotated[
        McpCursor | MISSING,
        Field(
            description=(
                "Cursor продолжения чтения. Поле следует опустить для первого chunk; "
                "JSON null не допускается."
            )
        ),
    ] = MISSING


McpContentReadItems = Annotated[
    tuple[ContentReadItem, ...],
    Field(
        min_length=1,
        max_length=8,
        description="От одного до восьми запросов чтения существующих ContentObjects.",
    ),
]
McpMaxChars = Annotated[
    int,
    Field(
        ge=1,
        le=30000,
        description="Максимальное число Unicode-символов в каждом возвращаемом chunk.",
    ),
]


class ContentGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: McpContentReadItems
    max_chars: McpMaxChars = 12000


McpContentIds = Annotated[
    tuple[McpContentId, ...],
    Field(
        min_length=1,
        max_length=8,
        description=(
            "От одного до восьми уникальных Content IDs для немедленного L1 Native Parsing."
        ),
        json_schema_extra={"uniqueItems": True},
    ),
]


class ContentParseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_ids: McpContentIds

    @model_validator(mode="after")
    def unique_content_ids(self) -> ContentParseInput:
        if len(self.content_ids) != len(set(self.content_ids)):
            raise ValueError("content_ids must be unique")
        return self


class ContentReadBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[BatchItemResult[ContentReadResult], ...] = Field(min_length=1, max_length=8)
