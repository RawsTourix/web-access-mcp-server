from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import AuthorizationError
from web_access.application.content.service import ContentApplicationService, ContentCursorError
from web_access.core.config import ContentStoreSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import ContentFormat, ContentRepresentationKind
from web_access.infrastructure.content import (
    FilesystemContentStore,
    HmacContentCursorCodec,
    RegistryContentIdentifier,
)
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _body(value: bytes) -> AsyncIterator[bytes]:
    midpoint = len(value) // 2
    yield value[:midpoint]
    yield value[midpoint:]


def _context(owner: str, clock: FakeClock, *, scoped: bool = True) -> ExecutionContext:
    scopes = frozenset({"content:read"}) if scoped else frozenset()
    return ExecutionContext(
        operation_id=f"op_{owner}",
        principal=PrincipalContext(owner, scopes),
        clock=clock,
        cancellation=CancellationToken(),
    )


def test_content_read_cursor_binary_and_authorized_stream(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content read tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(url)
        sessions = create_session_factory(engine)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(sessions)
        settings = ContentStoreSettings(root=tmp_path, chunk_size=4096)
        store = FilesystemContentStore(settings)
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter(uuid4().hex for _ in range(8))),
            uow_factory=uow_factory,
            store=store,
            identifier=RegistryContentIdentifier(available_formats=frozenset({ContentFormat.TEXT})),
            cursor_codec=HmacContentCursorCodec("integration-cursor-secret" * 3),
        )
        clock = FakeClock(datetime(2026, 8, 11, tzinfo=UTC))
        owner = _context("read-owner", clock)
        text = "A😀Бe\u0301終Z"
        text_ref = await service.ingest(
            owner,
            _body(text.encode()),
            representation_kind=ContentRepresentationKind.TEXT,
            media_type="text/plain; charset=utf-8",
            source_filename="notes.txt",
        )

        chunks = []
        cursor = None
        first_cursor = None
        while True:
            result = await service.read(owner, text_ref.content_id, max_chars=2, cursor=cursor)
            assert result.returned_chars <= 2
            assert result.returned_chars == len(result.text or "")
            chunks.append(result.text or "")
            cursor = result.next_cursor
            if first_cursor is None:
                first_cursor = cursor
            if cursor is None:
                break
        assert "".join(chunks) == text
        assert first_cursor is not None and len(first_cursor) <= 2048

        tampered = first_cursor[:-1] + ("A" if first_cursor[-1] != "A" else "B")
        with pytest.raises(ContentCursorError, match="tampered"):
            await service.read(owner, text_ref.content_id, cursor=tampered)
        with pytest.raises(AuthorizationError):
            await service.read(_context("other-owner", clock), text_ref.content_id)
        with pytest.raises(AuthorizationError):
            await service.read(_context("read-owner", clock, scoped=False), text_ref.content_id)
        with pytest.raises(ContentCursorError, match="size bound"):
            await service.read(owner, text_ref.content_id, cursor="x" * 2049)

        other_text_ref = await service.ingest(
            owner,
            _body(b"another text resource"),
            representation_kind=ContentRepresentationKind.TEXT,
            media_type="text/plain; charset=utf-8",
        )
        with pytest.raises(ContentCursorError, match="does not match"):
            await service.read(owner, other_text_ref.content_id, cursor=first_cursor)

        await service.inspect(owner, text_ref.content_id)
        with pytest.raises(ContentCursorError, match="revision"):
            await service.read(owner, text_ref.content_id, cursor=first_cursor)

        binary = b"\x00\xff\x89PNG\r\n"
        binary_ref = await service.ingest(
            owner,
            _body(binary),
            representation_kind=ContentRepresentationKind.BINARY,
            media_type="image/png",
            source_filename="..\\unsafe\r\nname.png",
        )
        binary_result = await service.read(owner, binary_ref.content_id)
        assert binary_result.text is None
        assert binary_result.returned_chars == 0
        with pytest.raises(ContentCursorError, match="binary"):
            await service.read(owner, binary_ref.content_id, cursor=first_cursor)

        authorized = await service.open_data(owner, binary_ref.content_id)
        assert authorized.content == binary_ref
        assert b"".join([chunk async for chunk in authorized.stream]) == binary
        assert not hasattr(authorized, "storage_key")
        await engine.dispose()

    asyncio.run(run())
