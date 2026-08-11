from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from web_access.core.config import ContentStoreSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import (
    ContentId,
    ContentObject,
    ContentRepresentationKind,
    ContentState,
)
from web_access.infrastructure.content import FilesystemContentStore
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _upgrade(url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def test_two_reconcilers_converge_and_remove_only_old_orphan_staging(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content maintenance tests")
    _upgrade(url)

    async def run() -> None:
        now = datetime(2026, 8, 11, 12, tzinfo=UTC)
        engine = create_async_engine(url)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(create_session_factory(engine))
        store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
        content_id = ContentId(f"cnt_{uuid4().hex}")
        async with uow_factory() as uow:
            await uow.contents.add(
                ContentObject(
                    content_id=content_id,
                    owner_principal_id="maintenance-owner",
                    state=ContentState.CREATING,
                    revision=1,
                    representation_kind=ContentRepresentationKind.RAW,
                    created_at=now - timedelta(hours=2),
                )
            )
            await uow.commit()
        staged = await store.stage_write(str(content_id), _chunks(b"recoverable"))
        async with uow_factory() as uow:
            assert await uow.contents.set_staged(
                content_id,
                expected_revision=1,
                staging_key=staged.handle,
                sha256=staged.sha256,
                size_bytes=staged.size,
            )
            await uow.commit()
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE content_objects SET updated_at=:old WHERE content_id=:content_id"),
                {"old": now - timedelta(hours=2), "content_id": str(content_id)},
            )

        orphan_id = f"cnt_{uuid4().hex}"
        orphan = await store.stage_write(orphan_id, _chunks(b"orphan"))
        orphan_path = tmp_path / orphan.handle
        old_epoch = (now - timedelta(hours=2)).timestamp()
        os.utime(orphan_path, (old_epoch, old_epoch))

        maintenance = ContentMaintenanceService(
            clock=FakeClock(now),
            uow_factory=uow_factory,
            store=store,
            stale_after_seconds=60,
            gc_grace_seconds=60,
            batch_size=100,
        )
        await asyncio.gather(maintenance.run_once(), maintenance.run_once())

        async with uow_factory() as uow:
            recovered = await uow.contents.get(content_id)
            assert recovered is not None
            assert recovered.content.state is ContentState.AVAILABLE
            assert recovered.storage_key is not None
        assert await store.stat_staging(orphan.handle) is None
        assert await store.stat(recovered.storage_key) is not None
        await engine.dispose()

    asyncio.run(run())


def test_gc_is_reference_aware_for_same_hash_across_owners(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content maintenance tests")
    _upgrade(url)

    async def run() -> None:
        now = datetime(2026, 8, 11, 12, tzinfo=UTC)
        engine = create_async_engine(url)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(create_session_factory(engine))
        store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
        values = (uuid4().hex, uuid4().hex)
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter(values)),
            uow_factory=uow_factory,
            store=store,
        )

        def context(owner: str) -> ExecutionContext:
            return ExecutionContext(
                operation_id=f"op_{owner}",
                principal=PrincipalContext(owner, frozenset({"content:write"})),
                clock=FakeClock(now),
                cancellation=CancellationToken(),
            )

        first = await service.ingest(
            context("owner-a"),
            _chunks(b"shared bytes"),
            representation_kind=ContentRepresentationKind.RAW,
        )
        second = await service.ingest(
            context("owner-b"),
            _chunks(b"shared bytes"),
            representation_kind=ContentRepresentationKind.RAW,
        )
        async with uow_factory() as uow:
            first_record = await uow.contents.get(ContentId(first.content_id))
            second_record = await uow.contents.get(ContentId(second.content_id))
            assert first_record is not None and second_record is not None
            assert first_record.storage_key == second_record.storage_key
            assert first_record.storage_key is not None
            shared_key = first_record.storage_key

        maintenance = ContentMaintenanceService(
            clock=FakeClock(now + timedelta(hours=2)),
            uow_factory=uow_factory,
            store=store,
            stale_after_seconds=60,
            gc_grace_seconds=60,
            batch_size=100,
        )
        old = now - timedelta(hours=1)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE content_objects SET state='deleted', updated_at=:old "
                    "WHERE content_id=:content_id"
                ),
                {"old": old, "content_id": first.content_id},
            )
        await maintenance.run_once()
        assert await store.stat(shared_key) is not None

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE content_objects SET state='deleted', updated_at=:old "
                    "WHERE content_id=:content_id"
                ),
                {"old": old, "content_id": second.content_id},
            )
        result = await maintenance.run_once()
        assert result.final_blobs_removed == 1
        assert await store.stat(shared_key) is None
        await engine.dispose()

    asyncio.run(run())
