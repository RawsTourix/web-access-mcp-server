from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.content.maintenance import ContentMaintenanceService
from web_access.application.content.service import ContentApplicationService
from web_access.core.config import ContentStoreSettings, ParserSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import ContentId, ContentRepresentationKind
from web_access.infrastructure.content import (
    FilesystemContentStore,
    HmacContentCursorCodec,
    RegistryContentIdentifier,
)
from web_access.infrastructure.content.parsers import (
    ContentNativeParserRegistry,
    InlineNativeParserExecutor,
    JsonNativeParser,
)
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _chunks(data: bytes, chunk_size: int = 4096) -> AsyncIterator[bytes]:
    for offset in range(0, len(data), chunk_size):
        yield data[offset : offset + chunk_size]


def _upgrade(url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def test_content_store_representation_and_cursor_soak_converges(
    tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content soak tests")
    _upgrade(url)

    async def run() -> tuple[int, int, int]:
        now = datetime(2026, 8, 14, 12, tzinfo=UTC)
        engine = create_async_engine(url)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(create_session_factory(engine))
        store = FilesystemContentStore(ContentStoreSettings(root=tmp_path, chunk_size=4096))
        parser_settings = ParserSettings()
        registry = ContentNativeParserRegistry((JsonNativeParser(parser_settings),))
        cursor_codec = HmacContentCursorCodec("content-soak-cursor-key-material-32-bytes")
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter(uuid4().hex for _ in range(128))),
            uow_factory=uow_factory,
            store=store,
            identifier=RegistryContentIdentifier(available_formats=registry.available_formats),
            parser_registry=registry,
            parser_executor=InlineNativeParserExecutor(),
            cursor_codec=cursor_codec,
        )
        context = ExecutionContext(
            operation_id="op_content_soak",
            principal=PrincipalContext(
                "content-soak-owner", frozenset({"content:read", "content:write"})
            ),
            clock=FakeClock(now),
            cancellation=CancellationToken(),
        )

        nonce = uuid4().hex
        raw_data = f'{{"stable":"same-hash","nonce":"{nonce}"}}'.encode()
        sources = []
        for _wave in range(3):
            wave = await asyncio.gather(
                *(
                    service.ingest(
                        context,
                        _chunks(raw_data),
                        representation_kind=ContentRepresentationKind.RAW,
                        media_type="application/json",
                        source_filename="same.json",
                    )
                    for _ in range(6)
                )
            )
            sources.extend(wave)
            assert await store.list_staging(100) == ()

        async with uow_factory() as uow:
            records = [await uow.contents.get(ContentId(source.content_id)) for source in sources]
        storage_keys = {record.storage_key for record in records if record is not None}
        assert len(storage_keys) == 1
        assert len(await store.list_final(100)) == 1

        parses = await asyncio.gather(
            *(service.native_parse(context, sources[0].content_id) for _ in range(12))
        )
        replay = [await service.native_parse(context, sources[0].content_id) for _ in range(12)]
        identities = {
            tuple(item.content_id for item in result.representations)
            for result in (*parses, *replay)
        }
        assert len(identities) == 1
        assert all(result.reused for result in replay)
        async with uow_factory() as uow:
            relations = await uow.relations.for_source(ContentId(sources[0].content_id))
        assert len(relations) == 1

        text_data = ("stateless cursor line\n" * 800).encode()
        readable = await service.ingest(
            context,
            _chunks(text_data),
            representation_kind=ContentRepresentationKind.TEXT,
            media_type="text/plain",
            source_filename="cursor.txt",
        )
        cursor_state_before = dict(vars(cursor_codec))
        read_calls = 0
        for _scan in range(8):
            cursor = None
            parts: list[str] = []
            while True:
                page = await service.read(
                    context, readable.content_id, max_chars=1024, cursor=cursor
                )
                read_calls += 1
                parts.append(page.text or "")
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert "".join(parts).encode() == text_data
        assert vars(cursor_codec) == cursor_state_before

        orphan = await store.stage_write(f"cnt_{uuid4().hex}", _chunks(b"orphan"))
        old = now - timedelta(hours=2)
        orphan_path = tmp_path / orphan.handle
        old_epoch = old.timestamp()
        os.utime(orphan_path, (old_epoch, old_epoch))
        async with engine.begin() as connection:
            for source in sources:
                await connection.execute(
                    text(
                        "UPDATE content_objects SET state='deleted', updated_at=:old "
                        "WHERE content_id=:content_id"
                    ),
                    {"old": old, "content_id": source.content_id},
                )

        maintenance = ContentMaintenanceService(
            clock=FakeClock(now),
            uow_factory=uow_factory,
            store=store,
            stale_after_seconds=60,
            gc_grace_seconds=60,
            batch_size=1000,
        )
        results = await asyncio.gather(*(maintenance.run_once() for _ in range(3)))
        assert sum(item.orphan_staging_removed for item in results) == 1
        assert sum(item.final_blobs_removed for item in results) >= 1
        assert await store.stat_staging(orphan.handle) is None
        assert await store.list_staging(100) == ()
        remaining_blobs = len(await store.list_final(100))
        assert remaining_blobs == 2
        await engine.dispose()
        return len(sources), read_calls, remaining_blobs

    sources, read_calls, remaining_blobs = asyncio.run(run())
    record_property("content_soak_sources", sources)
    record_property("content_soak_cursor_reads", read_calls)
    record_property("content_soak_remaining_blobs", remaining_blobs)
