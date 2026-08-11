"""Application-owned Safe Retrieval transport port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from web_access.application.common.context import ExecutionContext
from web_access.domain.retrieval import RetrievedResource


@dataclass(slots=True)
class SafeFetchResponse:
    metadata: RetrievedResource
    body: AsyncIterator[bytes]


class SafeHttpFetcher(Protocol):
    async def fetch(self, context: ExecutionContext, url: str) -> SafeFetchResponse: ...
