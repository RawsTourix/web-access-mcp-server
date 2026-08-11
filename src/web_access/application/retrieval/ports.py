"""Application-owned Safe Retrieval transport port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from web_access.application.common.context import ExecutionContext
from web_access.domain.retrieval import RedirectHop, RetrievedResource


@dataclass(slots=True)
class FetchCounters:
    wire_bytes: int = 0
    entity_bytes: int = 0


@dataclass(slots=True)
class SafeFetchResponse:
    requested_url: str
    final_url: str
    http_status: int
    redirect_chain: tuple[RedirectHop, ...]
    content_encoding: str | None
    declared_media_type: str | None
    source_filename: str | None
    body: AsyncIterator[bytes]
    counters: FetchCounters

    def metadata(self) -> RetrievedResource:
        return RetrievedResource(
            requested_url=self.requested_url,
            final_url=self.final_url,
            http_status=self.http_status,
            redirect_chain=self.redirect_chain,
            wire_bytes=self.counters.wire_bytes,
            entity_bytes=self.counters.entity_bytes,
            content_encoding=self.content_encoding,
            declared_media_type=self.declared_media_type,
            source_filename=self.source_filename,
        )


class SafeHttpFetcher(Protocol):
    async def fetch(self, context: ExecutionContext, url: str) -> SafeFetchResponse: ...
