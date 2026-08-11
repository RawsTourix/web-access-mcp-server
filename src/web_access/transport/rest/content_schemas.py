"""Strict REST v1 Content batch request schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RestContentIdsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_ids: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = Field(
        min_length=1,
        max_length=32,
        json_schema_extra={"uniqueItems": True},
    )

    @model_validator(mode="after")
    def unique_content_ids(self) -> RestContentIdsRequest:
        if len(self.content_ids) != len(set(self.content_ids)):
            raise ValueError("content_ids must be unique")
        return self


class RestNativeParseRequest(RestContentIdsRequest):
    reuse_existing: bool = True
