"""Long-lived aiohttp lifecycle with validated DNS/connect semantics."""

from __future__ import annotations

import asyncio
import ssl

from aiohttp import (
    ClientResponse,
    ClientSession,
    ClientTimeout,
    DummyCookieJar,
    TCPConnector,
)
from aiohttp.abc import AbstractResolver

from web_access.core.config import RetrievalSettings
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import RetrievalUrlPolicy


class SafeAioHttpClient:
    def __init__(
        self,
        *,
        settings: RetrievalSettings,
        policy: RetrievalUrlPolicy,
        resolver: AbstractResolver | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._settings = settings
        self._policy = policy
        self._resolver = resolver or ValidatingResolver(policy)
        self._ssl_context = ssl_context
        self._session: ClientSession | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._session is not None and not self._session.closed

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self.started:
                return
            connector = TCPConnector(
                resolver=self._resolver,
                use_dns_cache=False,
                limit=self._settings.max_connections,
                limit_per_host=self._settings.max_connections_per_host,
                enable_cleanup_closed=True,
                ssl=self._ssl_context or True,
            )
            self._session = ClientSession(
                connector=connector,
                trust_env=False,
                cookie_jar=DummyCookieJar(),
                auto_decompress=False,
                headers={"Accept-Encoding": "identity"},
            )

    async def get(self, url: str, *, timeout_seconds: float) -> ClientResponse:
        validated = self._policy.validate_url(url)
        await self.start()
        session = self._session
        if session is None:
            raise RuntimeError("Retrieval client failed to start")
        return await session.get(
            validated.normalized_url,
            allow_redirects=False,
            timeout=ClientTimeout(total=timeout_seconds),
        )

    async def close(self) -> None:
        async with self._lifecycle_lock:
            session = self._session
            self._session = None
            if session is not None:
                await session.close()
