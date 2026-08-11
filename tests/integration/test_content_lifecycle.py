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
from web_access.application.content.service import ContentApplicationService
from web_access.core.config import ContentStoreSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import ContentId, ContentRepresentationKind, ContentState
from web_access.infrastructure.content import FilesystemContentStore
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data[:7]
    yield data[7:]


def test_content_creation_publishes_only_after_staging_and_cas(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content lifecycle tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(url)
        sessions = create_session_factory(engine)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(sessions)
        store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
        value = uuid4().hex
        clock = FakeClock(datetime(2026, 8, 11, tzinfo=UTC))
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter((value,))),
            uow_factory=uow_factory,
            store=store,
        )
        context = ExecutionContext(
            operation_id="op_test",
            principal=PrincipalContext("owner-a", frozenset({"content:write"})),
            clock=clock,
            cancellation=CancellationToken(),
        )
        data = b"durable content lifecycle"

        reference = await service.ingest(
            context,
            _chunks(data),
            representation_kind=ContentRepresentationKind.RAW,
            media_type="text/plain",
            source_filename="safe.txt",
        )

        assert reference.content_id == f"cnt_{value}"
        assert reference.size_bytes == len(data)
        assert "storage_key" not in reference.model_dump()
        async with uow_factory() as uow:
            record = await uow.contents.get(ContentId(reference.content_id))
            assert record is not None
            assert record.content.state is ContentState.AVAILABLE
            assert record.content.revision == 3
            assert record.storage_key is not None
            assert record.staging_key is None
            stale = await uow.contents.publish(
                ContentId(reference.content_id),
                expected_revision=2,
                storage_key=record.storage_key,
            )
            assert stale is None

        assert b"".join([chunk async for chunk in store.open_stream(record.storage_key)]) == data
        await engine.dispose()

    asyncio.run(run())
