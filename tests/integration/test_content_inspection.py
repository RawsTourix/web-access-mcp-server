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
from web_access.application.content.service import ContentApplicationService
from web_access.core.config import ContentStoreSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import ContentFormat, ContentId, ContentRepresentationKind
from web_access.infrastructure.content import FilesystemContentStore, RegistryContentIdentifier
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _context(owner: str, clock: FakeClock) -> ExecutionContext:
    return ExecutionContext(
        operation_id=f"op_{owner}",
        principal=PrincipalContext(owner, frozenset({"content:read", "content:write"})),
        clock=clock,
        cancellation=CancellationToken(),
    )


def test_inspection_is_owner_scoped_cas_persisted_and_reused(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content inspection tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(url)
        sessions = create_session_factory(engine)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(sessions)
        settings = ContentStoreSettings(
            root=tmp_path,
            chunk_size=4096,
            inspection_sample_bytes=4096,
        )
        store = FilesystemContentStore(settings)
        value = uuid4().hex
        clock = FakeClock(datetime(2026, 8, 11, tzinfo=UTC))
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter((value,))),
            uow_factory=uow_factory,
            store=store,
            identifier=RegistryContentIdentifier(available_formats=frozenset({ContentFormat.PDF})),
            inspection_sample_bytes=settings.inspection_sample_bytes,
            max_inspection_json_bytes=settings.max_inspection_json_bytes,
        )
        owner = _context("owner-inspection", clock)
        reference = await service.ingest(
            owner,
            _body(b"%PDF-1.7\n" + b"x" * 8192),
            representation_kind=ContentRepresentationKind.RAW,
            media_type="text/plain",
            source_filename="document.txt",
        )

        with pytest.raises(AuthorizationError):
            await service.inspect(_context("other-owner", clock), reference.content_id)

        first = await service.inspect(owner, reference.content_id)
        assert first.detected_format is ContentFormat.PDF
        assert first.size_bytes == reference.size_bytes
        assert first.sha256 == reference.sha256
        assert first.warnings[0].code == "declared_content_type_mismatch"

        async with uow_factory() as uow:
            record = await uow.contents.get(ContentId(reference.content_id))
            assert record is not None
            assert record.content.revision == 4
            assert record.inspection == first
            assert record.storage_key is not None
            storage_key = record.storage_key

        assert await store.remove(storage_key)
        second = await service.inspect(owner, reference.content_id)
        assert second == first
        await engine.dispose()

    asyncio.run(run())
