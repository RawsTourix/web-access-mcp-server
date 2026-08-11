"""Strict REST v1 Retrieval request schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from web_access.domain.retrieval import (
    RetrievalBatchRequest,
    RetrievalProcessingLevel,
    RetrievalRequestItem,
)


class RestFetchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=8192)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        RetrievalRequestItem(value)
        return value


class RestFetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[RestFetchItem, ...] = Field(min_length=1, max_length=32)
    processing_level: RetrievalProcessingLevel = RetrievalProcessingLevel.NATIVE

    def to_application(self) -> RetrievalBatchRequest:
        return RetrievalBatchRequest(
            tuple(RetrievalRequestItem(item.url) for item in self.items),
            self.processing_level,
        )
