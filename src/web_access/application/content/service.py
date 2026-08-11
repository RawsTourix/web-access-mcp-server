"""Content lifecycle orchestration over application-owned ports."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable

from web_access.application.common.content_store import ContentStore, StagedBlob
from web_access.application.common.context import ExecutionContext
from web_access.application.content.models import ContentRef
from web_access.application.content.ports import ContentUnitOfWorkFactory
from web_access.core.ids import IdGenerator, IdPrefix
from web_access.domain.content import (
    ContentId,
    ContentObject,
    ContentRepresentationKind,
    ContentState,
)


class ContentLifecycleError(RuntimeError):
    pass


class ContentApplicationService:
    def __init__(
        self,
        *,
        ids: IdGenerator,
        uow_factory: ContentUnitOfWorkFactory,
        store: ContentStore,
    ) -> None:
        self._ids = ids
        self._uow_factory = uow_factory
        self._store = store

    async def ingest(
        self,
        context: ExecutionContext,
        stream: AsyncIterable[bytes],
        *,
        representation_kind: ContentRepresentationKind,
        media_type: str | None = None,
        source_filename: str | None = None,
    ) -> ContentRef:
        content_id = ContentId(self._ids.new(IdPrefix.CONTENT))
        created = ContentObject(
            content_id=content_id,
            owner_principal_id=context.principal.principal_id,
            state=ContentState.CREATING,
            revision=1,
            representation_kind=representation_kind,
            created_at=context.clock.utc_now(),
            media_type=media_type,
            source_filename=source_filename,
        )
        async with self._uow_factory() as uow:
            await uow.contents.add(created)
            await uow.commit()

        staged: StagedBlob | None = None
        revision = 1
        try:
            staged = await self._store.stage_write(str(content_id), stream)
            async with self._uow_factory() as uow:
                record = await uow.contents.set_staged(
                    content_id,
                    expected_revision=revision,
                    staging_key=staged.handle,
                    sha256=staged.sha256,
                    size_bytes=staged.size,
                )
                if record is None or record.content.revision != 2:
                    raise ContentLifecycleError("staged Content CAS failed")
                await uow.commit()
            revision = 2
            final = await self._store.finalize(staged)
            async with self._uow_factory() as uow:
                published = await uow.contents.publish(
                    content_id, expected_revision=revision, storage_key=final.key
                )
                if published is None or published.content.state is not ContentState.AVAILABLE:
                    raise ContentLifecycleError("Content publication CAS failed")
                await uow.commit()
            return _content_ref(published.content)
        except asyncio.CancelledError:
            await self._cleanup_failed(content_id, revision, staged, "cancelled")
            raise
        except Exception:
            await self._cleanup_failed(content_id, revision, staged, "content_creation_failed")
            raise

    async def _cleanup_failed(
        self,
        content_id: ContentId,
        revision: int,
        staged: StagedBlob | None,
        failure_code: str,
    ) -> None:
        if staged is not None:
            try:
                await self._store.remove_staging(staged.handle)
            except (OSError, ValueError):
                pass
        try:
            async with self._uow_factory() as uow:
                await uow.contents.mark_failed(
                    content_id, expected_revision=revision, failure_code=failure_code
                )
                await uow.commit()
        except (OSError, RuntimeError):
            pass


def _content_ref(content: ContentObject) -> ContentRef:
    if content.size_bytes is None or content.sha256 is None:
        raise ContentLifecycleError("available Content lacks integrity metadata")
    return ContentRef(
        content_id=str(content.content_id),
        media_type=content.media_type,
        representation=content.representation_kind,
        size_bytes=content.size_bytes,
        sha256=content.sha256,
        created_at=content.created_at,
        expires_at=content.expires_at,
    )
