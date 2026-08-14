from __future__ import annotations

import asyncio
import gc
import hashlib
import ipaddress
import socket
import time
import tracemalloc
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from aiohttp.abc import AbstractResolver, ResolveResult

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory
from web_access.application.common.results import LeafOutcome, OperationOutcome
from web_access.application.content.models import ContentInspection, ContentRef, NativeParseResult
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.core.config import RetrievalSecuritySettings, RetrievalSettings
from web_access.core.time import SystemClock
from web_access.domain.content import ContentRepresentationKind
from web_access.domain.retrieval import (
    RetrievalBatchRequest,
    RetrievalProcessingLevel,
    RetrievalRequestItem,
)
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.fetcher import SafeHttpFetcher
from web_access.infrastructure.retrieval.resolver import ValidatingResolver
from web_access.infrastructure.retrieval.security import RetrievalUrlPolicy


class _LoopbackResolver(AbstractResolver):
    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
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


class _ControlledAddressValidator:
    def validate_addresses(self, addresses: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(ipaddress.ip_address(address) for address in addresses)


@dataclass(slots=True)
class _ServerStats:
    requests: int = 0
    connections: int = 0
    active: int = 0
    peak_active: int = 0
    bytes_sent: int = 0


@asynccontextmanager
async def _controlled_server(
    *,
    chunks: tuple[bytes, ...],
    response_delay: float = 0,
) -> AsyncIterator[tuple[int, _ServerStats]]:
    stats = _ServerStats()
    content_length = sum(map(len, chunks))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        stats.connections += 1
        try:
            while True:
                try:
                    await reader.readuntil(b"\r\n\r\n")
                except (asyncio.IncompleteReadError, ConnectionError):
                    return
                stats.requests += 1
                stats.active += 1
                stats.peak_active = max(stats.peak_active, stats.active)
                try:
                    if response_delay:
                        await asyncio.sleep(response_delay)
                    writer.write(
                        (
                            "HTTP/1.1 200 OK\r\n"
                            f"Content-Length: {content_length}\r\n"
                            "Content-Type: application/octet-stream\r\n"
                            "Connection: keep-alive\r\n\r\n"
                        ).encode("ascii")
                    )
                    for chunk in chunks:
                        writer.write(chunk)
                        stats.bytes_sent += len(chunk)
                        await writer.drain()
                finally:
                    stats.active -= 1
        except (ConnectionError, OSError):
            return
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port, stats
    finally:
        server.close()
        await server.wait_closed()


def _retrieval_components(
    port: int,
    *,
    batch_concurrency: int,
    connections_per_host: int,
    max_wire_bytes: int,
) -> tuple[RetrievalSettings, SafeHttpFetcher, SafeAioHttpClient]:
    security = RetrievalSecuritySettings(additional_allowed_ports=frozenset({port}))
    settings = RetrievalSettings(
        batch_concurrency=batch_concurrency,
        max_connections=connections_per_host,
        max_connections_per_host=connections_per_host,
        max_wire_bytes=max_wire_bytes,
        max_entity_bytes=max_wire_bytes,
        stream_chunk_size=64 * 1024,
        security=security,
    )
    policy = RetrievalUrlPolicy(security)
    resolver = ValidatingResolver(_ControlledAddressValidator(), _LoopbackResolver())
    client = SafeAioHttpClient(settings=settings, policy=policy, resolver=resolver)
    return settings, SafeHttpFetcher(client=client, policy=policy, settings=settings), client


def _context() -> ExecutionContext:
    return ExecutionContext(
        operation_id="op_retrieval_load",
        principal=PrincipalContext("load-owner", frozenset({"retrieval:read"})),
        clock=SystemClock(),
        cancellation=CancellationToken(),
    )


class _ContentSink:
    def __init__(self) -> None:
        self.calls = 0
        self.bytes_received = 0
        self.active = 0
        self.peak_active = 0

    async def ingest(
        self,
        context: ExecutionContext,
        stream: AsyncIterable[bytes],
        *,
        representation_kind: ContentRepresentationKind,
        media_type: str | None = None,
        source_filename: str | None = None,
    ) -> ContentRef:
        del context, media_type, source_filename
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        digest = hashlib.sha256()
        size = 0
        try:
            async for chunk in stream:
                digest.update(chunk)
                size += len(chunk)
        finally:
            self.active -= 1
        self.calls += 1
        self.bytes_received += size
        return ContentRef(
            content_id=f"cnt_{self.calls:032x}",
            representation=representation_kind,
            size_bytes=size,
            sha256=digest.hexdigest(),
            created_at=datetime(2026, 8, 14, tzinfo=UTC),
        )

    async def inspect(self, context: ExecutionContext, content_id: str) -> ContentInspection:
        del context, content_id
        raise AssertionError("STORE_ONLY load must not inspect Content")

    async def native_parse(self, context: ExecutionContext, content_id: str) -> NativeParseResult:
        del context, content_id
        raise AssertionError("STORE_ONLY load must not parse Content")


@pytest.mark.asyncio
async def test_controlled_retrieval_load_is_bounded_and_reuses_pool(
    record_property: Callable[[str, object], None],
) -> None:
    body = (b"bounded-load-block" * 2048)[: 32 * 1024]
    async with _controlled_server(chunks=(body,), response_delay=0.03) as (port, stats):
        settings, fetcher, client = _retrieval_components(
            port,
            batch_concurrency=4,
            connections_per_host=2,
            max_wire_bytes=64 * 1024,
        )
        sink = _ContentSink()
        service = RetrievalApplicationService(fetcher=fetcher, content=sink, settings=settings)
        request = RetrievalBatchRequest(
            items=tuple(
                RetrievalRequestItem(f"http://load.test:{port}/item/{index}") for index in range(12)
            ),
            processing_level=RetrievalProcessingLevel.STORE_ONLY,
        )
        started = time.perf_counter()
        try:
            result = await service.fetch(_context(), request)
        finally:
            await client.close()
        elapsed = time.perf_counter() - started

    throughput = sink.bytes_received / elapsed
    record_property("retrieval_bytes", sink.bytes_received)
    record_property("retrieval_elapsed_seconds", round(elapsed, 6))
    record_property("retrieval_bytes_per_second", round(throughput, 2))
    record_property("retrieval_peak_server_requests", stats.peak_active)
    record_property("retrieval_connections", stats.connections)

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data is not None
    assert all(item.outcome is LeafOutcome.SUCCEEDED for item in result.data.items)
    assert sink.calls == stats.requests == 12
    assert sink.bytes_received == stats.bytes_sent == len(body) * 12
    assert 2 <= stats.peak_active <= settings.max_connections_per_host
    assert stats.connections <= settings.max_connections
    assert sink.peak_active <= settings.batch_concurrency
    assert throughput > 0


def test_retrieval_batch_capacity_is_rejected_before_task_creation() -> None:
    with pytest.raises(ValueError, match="between 1 and 32"):
        RetrievalBatchRequest(
            items=tuple(
                RetrievalRequestItem(f"https://example.test/{index}") for index in range(33)
            )
        )


@pytest.mark.asyncio
async def test_load_capacity_failure_is_returned_as_structured_item() -> None:
    oversized = b"x" * (128 * 1024)
    async with _controlled_server(chunks=(oversized,)) as (port, _stats):
        settings, fetcher, client = _retrieval_components(
            port,
            batch_concurrency=2,
            connections_per_host=1,
            max_wire_bytes=64 * 1024,
        )
        sink = _ContentSink()
        service = RetrievalApplicationService(fetcher=fetcher, content=sink, settings=settings)
        request = RetrievalBatchRequest(
            items=(RetrievalRequestItem(f"http://capacity.test:{port}/oversized"),),
            processing_level=RetrievalProcessingLevel.STORE_ONLY,
        )
        try:
            result = await service.fetch(_context(), request)
        finally:
            await client.close()

    assert result.data is not None
    item = result.data.items[0]
    assert item.outcome is LeafOutcome.FAILED
    assert item.error is not None
    assert item.error.category is ErrorCategory.CAPACITY
    assert item.error.code == "response_too_large"
    assert sink.calls == 0


@pytest.mark.asyncio
async def test_large_stream_peak_memory_stays_below_full_entity_copy(
    record_property: Callable[[str, object], None],
) -> None:
    chunk = b"s" * (64 * 1024)
    chunks = (chunk,) * 96
    entity_bytes = len(chunk) * len(chunks)
    async with _controlled_server(chunks=chunks) as (port, stats):
        _settings, fetcher, client = _retrieval_components(
            port,
            batch_concurrency=1,
            connections_per_host=1,
            max_wire_bytes=8 * 1024 * 1024,
        )
        gc.collect()
        tracemalloc.start()
        try:
            response = await fetcher.fetch(_context(), f"http://stream.test:{port}/large")
            observed = 0
            async for part in response.body:
                observed += len(part)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            await client.close()

    record_property("stream_entity_bytes", entity_bytes)
    record_property("stream_peak_traced_bytes", peak)
    assert observed == stats.bytes_sent == entity_bytes
    assert peak < entity_bytes
