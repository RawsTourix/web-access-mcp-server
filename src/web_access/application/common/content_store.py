"""Application-consumer-owned physical ContentStore port."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredBlob:
    key: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class StagedBlob:
    """Opaque staged payload identity and incrementally computed integrity."""

    handle: str
    sha256: str
    size: int


class ContentStore(Protocol):
    async def stage_write(self, identity: str, stream: AsyncIterable[bytes]) -> StagedBlob: ...

    async def stat_staging(self, handle: str) -> StagedBlob | None: ...

    async def finalize(self, staged: StagedBlob) -> StoredBlob: ...

    async def remove_staging(self, handle: str) -> bool: ...

    async def write_stream(self, stream: AsyncIterable[bytes]) -> StoredBlob: ...

    def open_stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def stat(self, key: str) -> StoredBlob | None: ...

    async def exists(self, key: str) -> bool: ...

    async def remove(self, key: str) -> bool: ...

    async def probe(self) -> bool: ...
