"""Application-owned Content persistence, inspection, and parser ports."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from web_access.application.content.models import (
    ContentInspection,
    NativeParseResult,
    ParserDescriptor,
)
from web_access.domain.content import ContentId, ContentObject, ContentRelation, ContentState


@dataclass(frozen=True, slots=True)
class StagedBlob:
    handle: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FinalizedBlob:
    key: str
    sha256: str
    size_bytes: int


class ContentStore(Protocol):
    async def stage_write(self, identity: str, stream: AsyncIterable[bytes]) -> StagedBlob: ...

    async def stat_staging(self, handle: str) -> StagedBlob | None: ...

    async def finalize(self, staged: StagedBlob) -> FinalizedBlob: ...

    async def remove_staging(self, handle: str) -> bool: ...

    def open_stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def stat(self, key: str) -> FinalizedBlob | None: ...

    async def remove(self, key: str) -> bool: ...


class ContentRepository(Protocol):
    async def add(self, content: ContentObject) -> None: ...

    async def get(self, content_id: ContentId) -> ContentObject | None: ...

    async def transition(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        target: ContentState,
        storage_key: str | None = None,
        staging_key: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        failure_code: str | None = None,
    ) -> ContentObject | None: ...


class ContentRelationRepository(Protocol):
    async def add(self, relation: ContentRelation) -> None: ...

    async def for_source(self, source_content_id: ContentId) -> tuple[ContentRelation, ...]: ...


class ContentIdentifier(Protocol):
    async def inspect(
        self,
        data: bytes,
        *,
        declared_media_type: str | None,
        source_filename: str | None,
    ) -> ContentInspection: ...


class NativeParser(Protocol):
    @property
    def descriptor(self) -> ParserDescriptor: ...

    async def parse(self, source: ContentObject, data: bytes) -> NativeParseResult: ...


class NativeParserRegistry(Protocol):
    def select(self, inspection: ContentInspection) -> NativeParser | None: ...


class NativeParserExecutor(Protocol):
    async def execute(
        self, parser: NativeParser, source: ContentObject, data: bytes
    ) -> NativeParseResult: ...


class IsolatedParserExecutor(Protocol):
    async def execute(
        self, descriptor: ParserDescriptor, source: ContentObject, data: bytes
    ) -> NativeParseResult: ...
