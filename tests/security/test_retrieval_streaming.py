from __future__ import annotations

import asyncio
import ipaddress
import socket
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from aiohttp.abc import AbstractResolver, ResolveResult

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.core.config import RetrievalSecuritySettings, RetrievalSettings
from web_access.core.time import SystemClock
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.fetcher import (
    DecompressionLimitExceeded,
    RedirectBlocked,
    ResponseTooLarge,
    SafeHttpFetcher,
    UnsupportedContentEncoding,
)
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import RetrievalUrlPolicy

ResponsePayload = bytes | tuple[bytes, float, bytes]
ResponseFactory = Callable[[str], Awaitable[ResponsePayload]]


class LoopbackResolver(AbstractResolver):
    def __init__(self) -> None:
        self.calls = 0

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        self.calls += 1
        return [
            ResolveResult(
                hostname=host,
                host="127.0.0.1",
                port=port,
                family=socket.AF_INET,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
        ]

    async def close(self) -> None:
        return None


class TestOnlyLoopbackValidator:
    def validate_addresses(self, addresses: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(ipaddress.ip_address(address) for address in addresses)


def _context() -> ExecutionContext:
    return ExecutionContext(
        operation_id="op_stream",
        principal=PrincipalContext("test", frozenset({"retrieval:read"})),
        clock=SystemClock(),
        cancellation=CancellationToken(),
    )


async def _server(
    response_factory: ResponseFactory,
) -> AsyncIterator[tuple[int, list[str]]]:
    requests: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            target = request.split(b" ", 2)[1].decode("ascii")
            requests.append(target)
            response = await response_factory(target)
            if isinstance(response, tuple):
                headers, delay, body = response
                writer.write(headers)
                await writer.drain()
                await asyncio.sleep(delay)
                writer.write(body)
            else:
                writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, requests
    finally:
        server.close()
        await server.wait_closed()


def _response(
    body: bytes,
    *,
    headers: tuple[tuple[str, str], ...] = (),
    status: str = "200 OK",
) -> bytes:
    lines = [
        f"HTTP/1.1 {status}",
        f"Content-Length: {len(body)}",
        "Connection: close",
        *(f"{name}: {value}" for name, value in headers),
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii") + body


def _fetcher(
    port: int,
    *,
    max_decompression_ratio: float = 100.0,
    read_inactivity_seconds: float = 5.0,
) -> tuple[SafeHttpFetcher, SafeAioHttpClient, LoopbackResolver]:
    security = RetrievalSecuritySettings(additional_allowed_ports=frozenset({port}))
    settings = RetrievalSettings(
        max_wire_bytes=4096,
        max_entity_bytes=8192,
        stream_chunk_size=4096,
        max_decompression_ratio=max_decompression_ratio,
        read_inactivity_seconds=read_inactivity_seconds,
        security=security,
    )
    policy = RetrievalUrlPolicy(security)
    underlying = LoopbackResolver()
    resolver = ValidatingResolver(TestOnlyLoopbackValidator(), underlying)
    client = SafeAioHttpClient(settings=settings, policy=policy, resolver=resolver)
    return SafeHttpFetcher(client=client, policy=policy, settings=settings), client, underlying


async def _read(body: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in body])


@pytest.mark.asyncio
async def test_gzip_stream_reports_wire_and_entity_counts_and_safe_metadata() -> None:
    entity = b"retrieved content" * 20
    compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
    wire = compressor.compress(entity) + compressor.flush()

    async def respond(_target: str) -> bytes:
        return _response(
            wire,
            headers=(
                ("Content-Encoding", "gzip"),
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Disposition", 'attachment; filename="folder/file.txt"'),
            ),
        )

    async for port, requests in _server(respond):
        fetcher, client, resolver = _fetcher(port)
        try:
            result = await fetcher.fetch(_context(), f"http://content.test:{port}/gzip")
            assert await _read(result.body) == entity
            metadata = result.metadata()
        finally:
            await client.close()
        assert metadata.wire_bytes == len(wire)
        assert metadata.entity_bytes == len(entity)
        assert metadata.content_encoding == "gzip"
        assert metadata.declared_media_type == "text/plain"
        assert metadata.source_filename == "folder_file.txt"
        assert requests == ["/gzip"]
        assert resolver.calls == 1


@pytest.mark.asyncio
async def test_chunked_body_without_content_length_is_bounded_while_streaming() -> None:
    async def respond(_target: str) -> bytes:
        return (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n"
        )

    async for port, _requests in _server(respond):
        fetcher, client, _resolver = _fetcher(port)
        try:
            result = await fetcher.fetch(_context(), f"http://content.test:{port}/chunked")
            assert await _read(result.body) == b"abcde"
            assert result.metadata().wire_bytes == 5
            assert result.source_filename == "chunked"
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_declared_and_streamed_wire_limits_are_enforced() -> None:
    async def declared(_target: str) -> bytes:
        return b"HTTP/1.1 200 OK\r\nContent-Length: 9000\r\nConnection: close\r\n\r\n"

    async for port, _requests in _server(declared):
        fetcher, client, _resolver = _fetcher(port)
        try:
            with pytest.raises(ResponseTooLarge):
                await fetcher.fetch(_context(), f"http://content.test:{port}/declared")
        finally:
            await client.close()

    async def chunked(_target: str) -> bytes:
        body = b"x" * 4097
        return (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n" + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        )

    async for port, _requests in _server(chunked):
        fetcher, client, _resolver = _fetcher(port)
        try:
            result = await fetcher.fetch(_context(), f"http://content.test:{port}/streamed")
            with pytest.raises(ResponseTooLarge):
                await _read(result.body)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_decompression_ratio_and_unsupported_encoding_are_rejected() -> None:
    entity = b"a" * 5000
    compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
    wire = compressor.compress(entity) + compressor.flush()

    async def bomb(_target: str) -> bytes:
        return _response(wire, headers=(("Content-Encoding", "gzip"),))

    async for port, _requests in _server(bomb):
        fetcher, client, _resolver = _fetcher(port, max_decompression_ratio=2)
        try:
            result = await fetcher.fetch(_context(), f"http://content.test:{port}/bomb")
            with pytest.raises(DecompressionLimitExceeded):
                await _read(result.body)
        finally:
            await client.close()

    async def unsupported(_target: str) -> bytes:
        return _response(b"encoded", headers=(("Content-Encoding", "br"),))

    async for port, _requests in _server(unsupported):
        fetcher, client, _resolver = _fetcher(port)
        try:
            with pytest.raises(UnsupportedContentEncoding):
                await fetcher.fetch(_context(), f"http://content.test:{port}/unsupported")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_redirect_to_private_literal_is_rejected_before_second_request() -> None:
    async def respond(_target: str) -> bytes:
        return _response(
            b"",
            headers=(("Location", "http://127.0.0.1/private"),),
            status="302 Found",
        )

    async for port, requests in _server(respond):
        fetcher, client, resolver = _fetcher(port)
        try:
            with pytest.raises(RedirectBlocked):
                await fetcher.fetch(_context(), f"http://content.test:{port}/redirect")
        finally:
            await client.close()
        assert requests == ["/redirect"]
        assert resolver.calls == 1


@pytest.mark.asyncio
async def test_body_read_has_an_inactivity_timeout() -> None:
    async def slow_response(_target: str) -> ResponsePayload:
        return (
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\n",
            0.05,
            b"late",
        )

    async for port, _requests in _server(slow_response):
        fetcher, client, _resolver = _fetcher(port, read_inactivity_seconds=0.01)
        try:
            result = await fetcher.fetch(_context(), f"http://content.test:{port}/slow")
            with pytest.raises(TimeoutError):
                await _read(result.body)
        finally:
            await client.close()
