"""Runtime dependency binding for the mounted MCP transport."""

from __future__ import annotations

from typing import Protocol

from web_access.application.content.service import ContentApplicationService
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.application.search.service import SearchApplicationService
from web_access.core.config import Settings
from web_access.core.ids import IdGenerator
from web_access.core.time import Clock


class McpDependencies(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def ids(self) -> IdGenerator: ...

    @property
    def search(self) -> SearchApplicationService: ...

    @property
    def content(self) -> ContentApplicationService: ...

    @property
    def retrieval(self) -> RetrievalApplicationService: ...

    @property
    def settings(self) -> Settings: ...


class McpRuntimeBinding:
    """Bind one mounted MCP server to its bootstrap-owned runtime."""

    def __init__(self) -> None:
        self._dependencies: McpDependencies | None = None

    def bind(self, dependencies: McpDependencies) -> None:
        self._dependencies = dependencies

    def clear(self) -> None:
        self._dependencies = None

    def get(self) -> McpDependencies:
        if self._dependencies is None:
            raise RuntimeError("runtime dependencies are unavailable")
        return self._dependencies
