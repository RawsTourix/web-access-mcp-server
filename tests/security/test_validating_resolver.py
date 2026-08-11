from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator

import pytest
from aiohttp.abc import AbstractResolver, ResolveResult

from web_access.core.config import RetrievalSecuritySettings, RetrievalSettings
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import (
    BlockedDestinationError,
    RetrievalUrlPolicy,
)


class SequenceResolver(AbstractResolver):
    def __init__(self, answers: tuple[tuple[str, ...], ...]) -> None:
        self.answers = answers
        self.calls = 0
        self.closed = False

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return [
            ResolveResult(
                hostname=host,
                host=address,
                port=port,
                family=socket.AF_INET6 if ":" in address else socket.AF_INET,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
            for address in answer
        ]

    async def close(self) -> None:
        self.closed = True


class ControlledLoopbackPolicy:
    """Test-only validator proving connector address usage against a local server."""

    def validate_addresses(self, addresses: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(ipaddress.ip_address(address) for address in addresses)


async def _http_server() -> AsyncIterator[tuple[int, list[bytes]]]:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        requests.append(request)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
            b"Set-Cookie: session=must-not-persist\r\nConnection: close\r\n\r\nok"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, requests
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_mixed_dns_answer_is_rejected_as_a_whole() -> None:
    underlying = SequenceResolver((("8.8.8.8", "10.0.0.1"),))
    resolver = ValidatingResolver(RetrievalUrlPolicy(RetrievalSecuritySettings()), underlying)
    with pytest.raises(BlockedDestinationError):
        await resolver.resolve("mixed.test", 80)
    assert underlying.calls == 1
    await resolver.close()
    assert underlying.closed


@pytest.mark.asyncio
async def test_actual_connect_uses_first_validated_answer_without_second_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    async for port, requests in _http_server():
        url_policy = RetrievalUrlPolicy(
            RetrievalSecuritySettings(additional_allowed_ports=frozenset({port}))
        )
        underlying = SequenceResolver((("127.0.0.1",), ("10.0.0.1",)))
        validating = ValidatingResolver(ControlledLoopbackPolicy(), underlying)
        client = SafeAioHttpClient(
            settings=RetrievalSettings(
                max_connections=2,
                max_connections_per_host=1,
                security=RetrievalSecuritySettings(additional_allowed_ports=frozenset({port})),
            ),
            policy=url_policy,
            resolver=validating,
        )
        try:
            response = await client.get(f"http://rebind.test:{port}/resource", timeout_seconds=2)
            assert await response.read() == b"ok"
            assert response.url.host == "rebind.test"
        finally:
            await client.close()

        assert underlying.calls == 1
        assert len(requests) == 1
        request = requests[0].lower()
        assert b"host: rebind.test:" in request
        assert b"accept-encoding: identity" in request
        assert b"cookie:" not in request
