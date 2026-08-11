"""Bounded, multi-replica-safe Content reconciliation and physical GC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from web_access.application.common.content_store import ContentStore, StagedBlob
from web_access.application.content.ports import ContentRecord, ContentUnitOfWorkFactory
from web_access.core.time import Clock
from web_access.domain.content import ContentState


@dataclass(frozen=True, slots=True)
class ContentMaintenanceResult:
    recovered: int = 0
    failed_stale: int = 0
    orphan_staging_removed: int = 0
    final_blobs_removed: int = 0
    integrity_errors: int = 0


class ContentMaintenanceService:
    def __init__(
        self,
        *,
        clock: Clock,
        uow_factory: ContentUnitOfWorkFactory,
        store: ContentStore,
        stale_after_seconds: float,
        gc_grace_seconds: float,
        batch_size: int,
    ) -> None:
        if stale_after_seconds <= 0 or gc_grace_seconds <= 0:
            raise ValueError("Content maintenance ages must be positive")
        if not 1 <= batch_size <= 1000:
            raise ValueError("Content maintenance batch size is out of bounds")
        self._clock = clock
        self._uow_factory = uow_factory
        self._store = store
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._gc_grace = timedelta(seconds=gc_grace_seconds)
        self._batch_size = batch_size

    async def run_once(self) -> ContentMaintenanceResult:
        now = self._clock.utc_now()
        async with self._uow_factory() as uow:
            stale = await uow.contents.stale_creating(
                older_than=now - self._stale_after, limit=self._batch_size
            )
            known_staging = await uow.contents.known_staging_handles()

        recovered = 0
        failed_stale = 0
        for record in stale:
            if await self._recover(record):
                recovered += 1
            else:
                failed_stale += 1

        removed_staging = 0
        entries = await self._store.list_staging(self._batch_size)
        orphan_cutoff = now - self._stale_after
        for entry in entries:
            if entry.handle not in known_staging and entry.modified_at <= orphan_cutoff:
                removed_staging += int(await self._store.remove_staging(entry.handle))

        async with self._uow_factory() as uow:
            gc_candidates = await uow.contents.gc_storage_candidates(
                older_than=now - self._gc_grace, limit=self._batch_size
            )
        removed_final = 0
        for key in gc_candidates:
            async with self._uow_factory() as uow:
                await uow.contents.lock_storage_key(key)
                if not await uow.contents.has_active_storage_reference(key):
                    removed_final += int(await self._store.remove(key))
                await uow.commit()

        integrity_errors = 0
        async with self._uow_factory() as uow:
            available = await uow.contents.available_for_audit(limit=self._batch_size)
        for record in available:
            if record.storage_key is None:
                integrity_errors += 1
                continue
            observed = await self._store.stat(record.storage_key)
            if (
                observed is None
                or observed.sha256 != record.content.sha256
                or observed.size != record.content.size_bytes
            ):
                integrity_errors += 1

        return ContentMaintenanceResult(
            recovered=recovered,
            failed_stale=failed_stale,
            orphan_staging_removed=removed_staging,
            final_blobs_removed=removed_final,
            integrity_errors=integrity_errors,
        )

    async def _recover(self, record: ContentRecord) -> bool:
        content = record.content
        if content.state is not ContentState.CREATING:
            return False
        if record.staging_key is None or content.sha256 is None or content.size_bytes is None:
            async with self._uow_factory() as uow:
                failed = await uow.contents.mark_failed(
                    content.content_id,
                    expected_revision=content.revision,
                    failure_code="stale_creating",
                )
                if failed is not None:
                    await uow.commit()
                    return False
            return False
        staged = StagedBlob(
            handle=record.staging_key,
            sha256=content.sha256,
            size=content.size_bytes,
        )
        try:
            final = await self._store.finalize(staged)
        except (FileNotFoundError, OSError, ValueError):
            async with self._uow_factory() as uow:
                failed = await uow.contents.mark_failed(
                    content.content_id,
                    expected_revision=content.revision,
                    failure_code="staging_lost",
                )
                if failed is not None:
                    await uow.commit()
            return False
        async with self._uow_factory() as uow:
            await uow.contents.lock_storage_key(final.key)
            observed = await self._store.stat(final.key)
            if observed != final:
                return False
            published = await uow.contents.publish(
                content.content_id,
                expected_revision=content.revision,
                storage_key=final.key,
            )
            if published is None:
                existing = await uow.contents.get(content.content_id)
                return existing is not None and existing.content.state is ContentState.AVAILABLE
            await uow.commit()
            return True
