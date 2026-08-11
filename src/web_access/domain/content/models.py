"""Dependency-free Content resource values and lifecycle invariants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_CONTENT_ID = re.compile(r"^cnt_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContentState(StrEnum):
    CREATING = "creating"
    AVAILABLE = "available"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


class ContentRepresentationKind(StrEnum):
    RAW = "raw"
    TEXT = "text"
    MARKDOWN = "markdown"
    STRUCTURED = "structured"
    BINARY = "binary"


class ContentFormat(StrEnum):
    HTML = "html"
    TEXT = "text"
    JSON = "json"
    XML = "xml"
    CSV = "csv"
    PDF = "pdf"
    UNKNOWN = "unknown"


class ContentRelationType(StrEnum):
    DERIVED_FROM = "derived_from"


class ParserAvailability(StrEnum):
    AVAILABLE = "available"
    UNSUPPORTED = "unsupported"
    JOB_REQUIRED = "job_required"


_TRANSITIONS: dict[ContentState, frozenset[ContentState]] = {
    ContentState.CREATING: frozenset({ContentState.AVAILABLE, ContentState.FAILED}),
    ContentState.AVAILABLE: frozenset({ContentState.EXPIRED, ContentState.DELETED}),
    ContentState.FAILED: frozenset({ContentState.DELETED}),
    ContentState.EXPIRED: frozenset({ContentState.DELETED}),
    ContentState.DELETED: frozenset(),
}


def can_transition_content(current: ContentState, target: ContentState) -> bool:
    return target in _TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class ContentId:
    value: str

    def __post_init__(self) -> None:
        if _CONTENT_ID.fullmatch(self.value) is None:
            raise ValueError("invalid Content ID")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ContentObject:
    content_id: ContentId
    owner_principal_id: str
    state: ContentState
    revision: int
    representation_kind: ContentRepresentationKind
    created_at: datetime
    media_type: str | None = None
    detected_format: ContentFormat | None = None
    source_filename: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    expires_at: datetime | None = None
    source_content_id: ContentId | None = None
    producer_capability: str | None = None
    producer_revision: str | None = None
    representation_schema_revision: str | None = None
    processing_profile_revision: str | None = None
    parameters_hash: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.owner_principal_id) <= 128:
            raise ValueError("invalid Content owner")
        if self.revision < 1:
            raise ValueError("Content revision must be positive")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Content timestamp must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("Content size cannot be negative")
        if self.sha256 is not None and _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("invalid Content SHA-256")
        if (self.size_bytes is None) != (self.sha256 is None):
            raise ValueError("Content size and hash must be present together")
        if self.state is ContentState.AVAILABLE and self.sha256 is None:
            raise ValueError("available Content requires immutable integrity metadata")
        provenance = (
            self.producer_capability,
            self.producer_revision,
            self.representation_schema_revision,
            self.processing_profile_revision,
            self.parameters_hash,
        )
        if self.source_content_id is None:
            if any(value is not None for value in provenance):
                raise ValueError("root Content cannot carry derived provenance")
        elif any(value is None for value in provenance):
            raise ValueError("derived Content requires complete producer provenance")
        if self.source_content_id == self.content_id:
            raise ValueError("Content cannot derive from itself")
        if self.parameters_hash is not None and _SHA256.fullmatch(self.parameters_hash) is None:
            raise ValueError("invalid Content parameters hash")


@dataclass(frozen=True, slots=True)
class ContentRelation:
    source_content_id: ContentId
    target_content_id: ContentId
    relation_type: ContentRelationType
    created_at: datetime

    def __post_init__(self) -> None:
        if self.source_content_id == self.target_content_id:
            raise ValueError("Content cannot derive from itself")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Content relation timestamp must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
