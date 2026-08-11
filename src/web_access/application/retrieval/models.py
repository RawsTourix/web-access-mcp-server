"""Framework-independent Retrieval application result models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from web_access.application.common.results import BatchItemResult
from web_access.application.content.models import ContentInspection, ContentRef
from web_access.domain.retrieval import RedirectHop


class RetrievalItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    requested_url: str = Field(min_length=1, max_length=8192)
    final_url: str = Field(min_length=1, max_length=8192)
    http_status: int = Field(ge=100, le=599)
    redirect_chain: tuple[RedirectHop, ...] = Field(default=(), max_length=10)
    wire_bytes: int = Field(ge=0)
    entity_bytes: int = Field(ge=0)
    content_encoding: str | None = Field(default=None, max_length=64)
    raw_content: ContentRef
    inspection: ContentInspection | None = None
    native_content: ContentRef | None = None
    available_representations: tuple[ContentRef, ...] = Field(default=(), max_length=32)
    preview: str | None = Field(default=None, max_length=12000)


class RetrievalBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[BatchItemResult[RetrievalItemResult], ...] = Field(min_length=1, max_length=32)
