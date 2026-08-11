"""Application-owned Content persistence, inspection, and parser ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from pydantic import JsonValue

from web_access.application.common.content_store import (
    ContentStore,
    StagedBlob,
    StagingEntry,
    StoredBlob,
)
from web_access.application.content.models import (
    ContentInspection,
    NativeParserOutput,
    ParserDescriptor,
)
from web_access.domain.content import ContentId, ContentObject, ContentRelation

FinalizedBlob = StoredBlob


@dataclass(frozen=True, slots=True)
class ContentRecord:
    content: ContentObject
    storage_key: str | None = None
    staging_key: str | None = None
    staged_at: datetime | None = None
    available_at: datetime | None = None
    updated_at: datetime | None = None
    failure_code: str | None = None
    inspection: ContentInspection | None = None


@dataclass(frozen=True, slots=True)
class ContentRepresentationClaim:
    record: ContentRecord
    claimed: bool


class ContentRepository(Protocol):
    async def add(self, content: ContentObject) -> None: ...

    async def get(self, content_id: ContentId) -> ContentRecord | None: ...

    async def claim_representation(self, content: ContentObject) -> ContentRepresentationClaim: ...

    async def set_staged(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        staging_key: str,
        sha256: str,
        size_bytes: int,
    ) -> ContentRecord | None: ...

    async def publish(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        storage_key: str,
    ) -> ContentRecord | None: ...

    async def mark_failed(
        self, content_id: ContentId, *, expected_revision: int, failure_code: str
    ) -> ContentRecord | None: ...

    async def save_inspection(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        inspection: ContentInspection,
    ) -> ContentRecord | None: ...

    async def stale_creating(
        self, *, older_than: datetime, limit: int
    ) -> tuple[ContentRecord, ...]: ...

    async def known_staging_handles(self) -> frozenset[str]: ...

    async def gc_storage_candidates(
        self, *, older_than: datetime, limit: int
    ) -> tuple[str, ...]: ...

    async def lock_storage_key(self, storage_key: str) -> None: ...

    async def has_active_storage_reference(self, storage_key: str) -> bool: ...

    async def available_for_audit(self, *, limit: int) -> tuple[ContentRecord, ...]: ...


class ContentRelationRepository(Protocol):
    async def add(self, relation: ContentRelation) -> None: ...

    async def for_source(self, source_content_id: ContentId) -> tuple[ContentRelation, ...]: ...


class ContentIdentifier(Protocol):
    async def inspect(
        self,
        data: bytes,
        *,
        size_bytes: int,
        sha256: str,
        declared_media_type: str | None,
        source_filename: str | None,
    ) -> ContentInspection: ...


class NativeParser(Protocol):
    @property
    def descriptor(self) -> ParserDescriptor: ...

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput: ...


class NativeParserRegistry(Protocol):
    def select(self, inspection: ContentInspection) -> NativeParser | None: ...


class NativeParserExecutor(Protocol):
    async def execute(
        self,
        parser: NativeParser,
        source: ContentObject,
        inspection: ContentInspection,
        data: bytes,
    ) -> NativeParserOutput: ...


class IsolatedParserExecutor(Protocol):
    async def execute(
        self,
        parser_id: str,
        data: bytes,
        *,
        parameters: dict[str, JsonValue] | None = None,
    ) -> NativeParserOutput: ...


class ContentUnitOfWork(Protocol):
    @property
    def contents(self) -> ContentRepository: ...

    @property
    def relations(self) -> ContentRelationRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class ContentUnitOfWorkFactory(Protocol):
    def __call__(self) -> ContentUnitOfWork: ...


__all__ = [
    "ContentRecord",
    "ContentRelationRepository",
    "ContentRepository",
    "ContentStore",
    "ContentUnitOfWork",
    "ContentUnitOfWorkFactory",
    "FinalizedBlob",
    "IsolatedParserExecutor",
    "NativeParser",
    "NativeParserExecutor",
    "NativeParserRegistry",
    "StagedBlob",
    "StagingEntry",
]
