"""Framework-independent Content application and public projection models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from web_access.application.common.hints import StructuredHint, Warning
from web_access.domain.content import (
    ContentFormat,
    ContentRepresentationKind,
    ParserAvailability,
    ParserExecutionMode,
)

ContentIdValue = Annotated[str, Field(min_length=1, max_length=128)]


class ContentRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_id: ContentIdValue
    media_type: str | None = Field(default=None, max_length=255)
    representation: ContentRepresentationKind
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    expires_at: datetime | None = None


class ContentInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_revision: str = Field(default="content-inspection-v1", min_length=1, max_length=64)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_media_type: str | None = Field(default=None, max_length=255)
    detected_media_type: str | None = Field(default=None, max_length=255)
    detected_format: ContentFormat
    source_filename: str | None = Field(default=None, max_length=255)
    encoding: str | None = Field(default=None, max_length=64)
    parser_availability: ParserAvailability
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)


class ParserDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    revision: str = Field(min_length=1, max_length=128)
    profile_revision: str = Field(min_length=1, max_length=128)
    supported_formats: tuple[ContentFormat, ...] = Field(min_length=1, max_length=16)
    primary_representation: ContentRepresentationKind
    representation_schema_revision: str = Field(min_length=1, max_length=128)
    execution_mode: ParserExecutionMode = ParserExecutionMode.INLINE

    @model_validator(mode="after")
    def unique_formats(self) -> ParserDescriptor:
        if len(self.supported_formats) != len(set(self.supported_formats)):
            raise ValueError("duplicate supported Content format")
        return self


class NativeParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ContentRef
    representations: tuple[ContentRef, ...] = Field(default=(), max_length=8)
    reused: bool
    parser_capability: str | None = Field(default=None, max_length=64)
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)


class ParsedRepresentation(BaseModel):
    """Application-owned immutable parser output before durable publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    representation: ContentRepresentationKind
    media_type: str = Field(min_length=1, max_length=255)
    schema_revision: str = Field(min_length=1, max_length=128)
    data: bytes = Field(max_length=64 * 1024 * 1024)


class NativeParserOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    representations: tuple[ParsedRepresentation, ...] = Field(min_length=1, max_length=8)
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)


class ContentReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ContentRef
    text: str | None = None
    returned_chars: int = Field(ge=0, le=30000)
    next_cursor: str | None = Field(default=None, max_length=2048)
    inspection: ContentInspection | None = None
    available_representations: tuple[ContentRef, ...] = Field(default=(), max_length=32)
