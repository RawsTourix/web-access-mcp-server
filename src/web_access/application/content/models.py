"""Framework-independent Content application and public projection models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from web_access.application.common.hints import StructuredHint, Warning
from web_access.application.common.results import BatchItemResult
from web_access.domain.content import (
    ContentFormat,
    ContentRelationType,
    ContentRepresentationKind,
    ContentState,
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

    @model_validator(mode="after")
    def unique_representation_identities(self) -> NativeParserOutput:
        identities = [(item.representation, item.schema_revision) for item in self.representations]
        if len(identities) != len(set(identities)):
            raise ValueError("parser output contains duplicate representation identities")
        return self


class ContentReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ContentRef
    text: str | None = None
    returned_chars: int = Field(ge=0, le=30000)
    next_cursor: str | None = Field(default=None, max_length=2048)
    inspection: ContentInspection | None = None
    available_representations: tuple[ContentRef, ...] = Field(default=(), max_length=32)


class ContentProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_content_id: ContentIdValue
    producer_capability: str = Field(min_length=1, max_length=64)
    producer_revision: str = Field(min_length=1, max_length=128)
    representation_schema_revision: str = Field(min_length=1, max_length=128)
    processing_profile_revision: str = Field(min_length=1, max_length=128)


class ContentRetention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expires_at: datetime | None = None


class ContentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ContentRef
    state: ContentState
    representation_kind: ContentRepresentationKind
    media_type: str | None = Field(default=None, max_length=255)
    detected_format: ContentFormat | None = None
    source_filename: str | None = Field(default=None, max_length=255)
    inspection: ContentInspection | None = None
    provenance: ContentProvenance | None = None
    available_representations: tuple[ContentRef, ...] = Field(default=(), max_length=32)
    retention: ContentRetention


class ContentRepresentationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ContentRef
    relation_type: ContentRelationType
    representation_kind: ContentRepresentationKind
    provenance: ContentProvenance


class ContentRepresentationsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ContentRef
    representations: tuple[ContentRepresentationSummary, ...] = Field(default=(), max_length=32)


class ContentInspectResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ContentRef
    inspection: ContentInspection


class ContentInspectBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[BatchItemResult[ContentInspectResult], ...] = Field(min_length=1, max_length=32)


class ContentNativeParseBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[BatchItemResult[NativeParseResult], ...] = Field(min_length=1, max_length=32)
