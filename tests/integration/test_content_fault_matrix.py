from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Self, cast
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
from web_access.application.content.ports import (
    ContentRelationRepository,
    ContentRepository,
    ContentUnitOfWork,
    ContentUnitOfWorkFactory,
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


class InjectedLifecycleFailure(RuntimeError):
    pass


class _FaultingUnitOfWork:
    def __init__(self, delegate: ContentUnitOfWork, controller: _FaultingUnitOfWorkFactory) -> None:
        self._delegate = delegate
        self._controller = controller

    @property
    def contents(self) -> ContentRepository:
        return self._delegate.contents

    @property
    def relations(self) -> ContentRelationRepository:
        return self._delegate.relations

    async def __aenter__(self) -> Self:
        await self._delegate.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self._delegate.__aexit__(exc_type, exc_value, traceback)

    async def commit(self) -> None:
        self._controller.commit_count += 1
        selected = self._controller.commit_count == self._controller.fail_commit
        if selected and self._controller.timing == "before":
            raise InjectedLifecycleFailure("before commit")
        await self._delegate.commit()
        if selected and self._controller.timing == "after":
            raise InjectedLifecycleFailure("after commit")


class _FaultingUnitOfWorkFactory:
    def __init__(
        self,
        delegate: ContentUnitOfWorkFactory,
        *,
        fail_commit: int,
        timing: str,
    ) -> None:
        self._delegate = delegate
        self.fail_commit = fail_commit
        self.timing = timing
        self.commit_count = 0

    def __call__(self) -> ContentUnitOfWork:
        return _FaultingUnitOfWork(self._delegate(), self)


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


@pytest.mark.parametrize(
    "fault",
    [
        "after_row_reserve",
        "after_staging_write",
        "before_staged_metadata_commit",
        "after_staged_metadata_commit",
        "after_physical_finalization",
        "before_available_commit",
        "after_available_commit",
    ],
)
def test_content_lifecycle_failure_matrix_converges_without_published_partial(
    tmp_path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Content fault tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        now = datetime(2026, 8, 11, 12, tzinfo=UTC)
        engine = create_async_engine(url)
        base_factory = SqlAlchemyContentUnitOfWorkFactory(create_session_factory(engine))
        selected_factory: ContentUnitOfWorkFactory = base_factory
        commit_faults = {
            "after_row_reserve": (1, "after"),
            "before_staged_metadata_commit": (2, "before"),
            "after_staged_metadata_commit": (2, "after"),
            "before_available_commit": (3, "before"),
            "after_available_commit": (3, "after"),
        }
        if fault in commit_faults:
            commit_number, timing = commit_faults[fault]
            selected_factory = cast(
                ContentUnitOfWorkFactory,
                _FaultingUnitOfWorkFactory(base_factory, fail_commit=commit_number, timing=timing),
            )

        store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
        if fault == "after_staging_write":
            original_stage = store.stage_write

            async def fail_after_stage(identity: str, stream: AsyncIterator[bytes]):
                await original_stage(identity, stream)
                raise InjectedLifecycleFailure("after staging write")

            monkeypatch.setattr(store, "stage_write", fail_after_stage)
        elif fault == "after_physical_finalization":
            original_stat = store.stat
            failed = False

            async def fail_after_finalize(key: str):
                nonlocal failed
                if not failed:
                    failed = True
                    raise InjectedLifecycleFailure("after physical finalization")
                return await original_stat(key)

            monkeypatch.setattr(store, "stat", fail_after_finalize)

        value = uuid4().hex
        content_id = ContentId(f"cnt_{value}")
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter((value,))),
            uow_factory=selected_factory,
            store=store,
        )
        context = ExecutionContext(
            operation_id=f"op_{fault}",
            principal=PrincipalContext("fault-owner", frozenset({"content:write"})),
            clock=FakeClock(now),
            cancellation=CancellationToken(),
        )
        payload = f"fault:{fault}".encode()
        with pytest.raises(InjectedLifecycleFailure):
            await service.ingest(
                context,
                _body(payload),
                representation_kind=ContentRepresentationKind.RAW,
                media_type="application/octet-stream",
            )

        async with base_factory() as uow:
            initial = await uow.contents.get(content_id)
        assert initial is not None
        assert (
            initial.content.state is not ContentState.AVAILABLE or fault == "after_available_commit"
        )

        old = now - timedelta(hours=2)
        await store.start()
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE content_objects SET updated_at=:old WHERE content_id=:content_id"),
                {"old": old, "content_id": str(content_id)},
            )
        for entry in await store.list_staging(100):
            stage_path = tmp_path / entry.handle
            old_epoch = old.timestamp()
            os.utime(stage_path, (old_epoch, old_epoch))

        maintenance = ContentMaintenanceService(
            clock=FakeClock(now),
            uow_factory=base_factory,
            store=store,
            stale_after_seconds=60,
            gc_grace_seconds=60,
            batch_size=100,
        )
        await maintenance.run_once()

        async with base_factory() as uow:
            terminal = await uow.contents.get(content_id)
        assert terminal is not None
        expected = (
            ContentState.AVAILABLE if fault == "after_available_commit" else ContentState.FAILED
        )
        assert terminal.content.state is expected
        assert await store.list_staging(100) == ()
        digest = hashlib.sha256(payload).hexdigest()
        final_key = f"sha256/{digest[:2]}/{digest}"
        final = await store.stat(final_key)
        if expected is ContentState.AVAILABLE:
            assert final is not None
            assert terminal.storage_key == final_key
        else:
            assert final is None
        await engine.dispose()

    asyncio.run(run())
