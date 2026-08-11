"""Content lifecycle orchestration over application-owned ports."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable

from web_access.application.common.auth import require_owner
from web_access.application.common.content_store import ContentStore, StagedBlob
from web_access.application.common.context import ExecutionContext
from web_access.application.content.models import ContentInspection, ContentRef
from web_access.application.content.ports import ContentIdentifier, ContentUnitOfWorkFactory
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
        identifier: ContentIdentifier | None = None,
        inspection_sample_bytes: int = 256 * 1024,
        max_inspection_json_bytes: int = 64 * 1024,
    ) -> None:
        self._ids = ids
        self._uow_factory = uow_factory
        self._store = store
        self._identifier = identifier
        self._inspection_sample_bytes = inspection_sample_bytes
        self._max_inspection_json_bytes = max_inspection_json_bytes
        if inspection_sample_bytes < 1 or max_inspection_json_bytes < 1:
            raise ValueError("Content inspection limits must be positive")

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
                await uow.contents.lock_storage_key(final.key)
                observed_final = await self._store.stat(final.key)
                if observed_final != final:
                    raise ContentLifecycleError("final Content integrity verification failed")
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

    async def inspect(self, context: ExecutionContext, content_id: str) -> ContentInspection:
        identifier = self._identifier
        if identifier is None:
            raise ContentLifecycleError("Content identifier is not configured")
        typed_id = ContentId(content_id)
        async with self._uow_factory() as uow:
            record = await uow.contents.get(typed_id)
        if record is None:
            raise ContentLifecycleError("Content was not found")
        require_owner(context.principal, record.content.owner_principal_id)
        if record.content.state is not ContentState.AVAILABLE or record.storage_key is None:
            raise ContentLifecycleError("Content is not available")
        if record.inspection is not None:
            return record.inspection
        if record.content.size_bytes is None or record.content.sha256 is None:
            raise ContentLifecycleError("Content integrity metadata is missing")

        sample = await self._read_inspection_sample(record.storage_key)
        inspection = await identifier.inspect(
            sample,
            size_bytes=record.content.size_bytes,
            sha256=record.content.sha256,
            declared_media_type=record.content.media_type,
            source_filename=record.content.source_filename,
        )
        serialized_size = len(
            json.dumps(inspection.model_dump(mode="json"), ensure_ascii=False).encode()
        )
        if serialized_size > self._max_inspection_json_bytes:
            raise ContentLifecycleError("Content inspection exceeds persistence bound")
        async with self._uow_factory() as uow:
            saved = await uow.contents.save_inspection(
                typed_id,
                expected_revision=record.content.revision,
                inspection=inspection,
            )
            if saved is not None:
                await uow.commit()
                if saved.inspection is None:
                    raise ContentLifecycleError("saved Content inspection is missing")
                return saved.inspection
            winner = await uow.contents.get(typed_id)
        if winner is not None and winner.inspection is not None:
            return winner.inspection
        raise ContentLifecycleError("Content inspection CAS failed")

    async def _read_inspection_sample(self, storage_key: str) -> bytes:
        result = bytearray()
        stream = self._store.open_stream(storage_key)
        try:
            async for chunk in stream:
                remaining = self._inspection_sample_bytes - len(result)
                if remaining <= 0:
                    break
                result.extend(chunk[:remaining])
                if len(result) >= self._inspection_sample_bytes:
                    break
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return bytes(result)


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
