"""Content lifecycle orchestration over application-owned ports."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterable, AsyncIterator

from web_access.application.common.auth import require_owner
from web_access.application.common.content_store import ContentStore, StagedBlob
from web_access.application.common.context import ExecutionContext
from web_access.application.common.hints import Warning
from web_access.application.content.models import (
    ContentInspection,
    ContentRef,
    NativeParseResult,
    ParsedRepresentation,
    ParserDescriptor,
)
from web_access.application.content.ports import (
    ContentIdentifier,
    ContentUnitOfWorkFactory,
    NativeParserExecutor,
    NativeParserRegistry,
)
from web_access.core.ids import IdGenerator, IdPrefix
from web_access.domain.content import (
    ContentId,
    ContentObject,
    ContentRelation,
    ContentRelationType,
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
        parser_registry: NativeParserRegistry | None = None,
        parser_executor: NativeParserExecutor | None = None,
        inspection_sample_bytes: int = 256 * 1024,
        max_inspection_json_bytes: int = 64 * 1024,
        parser_input_bytes: int = 16 * 1024 * 1024,
        representation_wait_seconds: float = 10.0,
        representation_poll_seconds: float = 0.02,
    ) -> None:
        self._ids = ids
        self._uow_factory = uow_factory
        self._store = store
        self._identifier = identifier
        self._parser_registry = parser_registry
        self._parser_executor = parser_executor
        self._inspection_sample_bytes = inspection_sample_bytes
        self._max_inspection_json_bytes = max_inspection_json_bytes
        self._parser_input_bytes = parser_input_bytes
        self._representation_wait_seconds = representation_wait_seconds
        self._representation_poll_seconds = representation_poll_seconds
        if (
            min(
                inspection_sample_bytes,
                max_inspection_json_bytes,
                parser_input_bytes,
                representation_wait_seconds,
                representation_poll_seconds,
            )
            <= 0
        ):
            raise ValueError("Content processing limits must be positive")

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
        return await self._publish_created(stream, created)

    async def _publish_created(
        self,
        stream: AsyncIterable[bytes],
        created: ContentObject,
        relation: ContentRelation | None = None,
    ) -> ContentRef:
        async with self._uow_factory() as uow:
            await uow.contents.add(created)
            if relation is not None:
                await uow.relations.add(relation)
            await uow.commit()

        return await self._publish_reserved(stream, created)

    async def _publish_reserved(
        self,
        stream: AsyncIterable[bytes],
        created: ContentObject,
    ) -> ContentRef:
        content_id = created.content_id

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

    async def native_parse(self, context: ExecutionContext, content_id: str) -> NativeParseResult:
        registry = self._parser_registry
        executor = self._parser_executor
        if registry is None or executor is None:
            raise ContentLifecycleError("native parser runtime is not configured")
        typed_id = ContentId(content_id)
        inspection = await self.inspect(context, content_id)
        async with self._uow_factory() as uow:
            record = await uow.contents.get(typed_id)
        if (
            record is None
            or record.content.state is not ContentState.AVAILABLE
            or record.storage_key is None
        ):
            raise ContentLifecycleError("Content is not available")
        require_owner(context.principal, record.content.owner_principal_id)
        source_ref = _content_ref(record.content)
        parser = registry.select(inspection)
        if parser is None:
            return NativeParseResult(
                source=source_ref,
                reused=False,
                warnings=(
                    Warning(
                        code="native_parser_unavailable",
                        message="No registered native parser supports the detected Content format.",
                    ),
                ),
            )
        data = await self._read_bounded(record.storage_key, self._parser_input_bytes)
        output = await executor.execute(parser, record.content, inspection, data)
        representation_refs: list[ContentRef] = []
        created_any = False
        for parsed in output.representations:
            representation_ref, created_representation = await self._ingest_derived(
                context, record.content, parser.descriptor, parsed
            )
            representation_refs.append(representation_ref)
            created_any = created_any or created_representation
        return NativeParseResult(
            source=source_ref,
            representations=tuple(representation_refs),
            reused=not created_any,
            parser_capability=parser.descriptor.capability,
            warnings=output.warnings,
            hints=output.hints,
        )

    async def _ingest_derived(
        self,
        context: ExecutionContext,
        source: ContentObject,
        descriptor: ParserDescriptor,
        parsed: ParsedRepresentation,
    ) -> tuple[ContentRef, bool]:
        content_id = ContentId(self._ids.new(IdPrefix.CONTENT))
        created = ContentObject(
            content_id=content_id,
            owner_principal_id=context.principal.principal_id,
            state=ContentState.CREATING,
            revision=1,
            representation_kind=parsed.representation,
            created_at=context.clock.utc_now(),
            media_type=parsed.media_type,
            source_content_id=source.content_id,
            producer_capability=descriptor.capability,
            producer_revision=descriptor.revision,
            representation_schema_revision=parsed.schema_revision,
            processing_profile_revision=descriptor.profile_revision,
            parameters_hash=hashlib.sha256(b"{}").hexdigest(),
        )
        relation = ContentRelation(
            source_content_id=source.content_id,
            target_content_id=content_id,
            relation_type=ContentRelationType.DERIVED_FROM,
            created_at=context.clock.utc_now(),
        )
        wait_seconds = self._representation_wait_seconds
        if context.remaining_seconds() is not None:
            wait_seconds = min(wait_seconds, context.remaining_seconds() or 0)
        loop = asyncio.get_running_loop()
        wait_deadline = loop.time() + wait_seconds
        while True:
            if context.cancellation.requested:
                raise asyncio.CancelledError
            claimed = False
            async with self._uow_factory() as uow:
                claim = await uow.contents.claim_representation(created)
                if claim.claimed:
                    await uow.relations.add(relation)
                    await uow.commit()
                    claimed = True
                existing = claim.record
            if claimed:
                published = await self._publish_reserved(_single_chunk(parsed.data), created)
                return published, True
            if existing.content.state is ContentState.AVAILABLE:
                return _content_ref(existing.content), False
            remaining_wait = wait_deadline - loop.time()
            if remaining_wait <= 0:
                raise ContentLifecycleError("compatible Content representation wait expired")
            await asyncio.sleep(min(self._representation_poll_seconds, remaining_wait))

    async def _read_inspection_sample(self, storage_key: str) -> bytes:
        return await self._read_bounded(storage_key, self._inspection_sample_bytes, strict=False)

    async def _read_bounded(self, storage_key: str, limit: int, *, strict: bool = True) -> bytes:
        result = bytearray()
        stream = self._store.open_stream(storage_key)
        try:
            async for chunk in stream:
                remaining = limit - len(result)
                if remaining <= 0:
                    if strict:
                        raise ContentLifecycleError("Content exceeds parser input limit")
                    break
                result.extend(chunk[: remaining + (1 if strict else 0)])
                if len(result) > limit:
                    raise ContentLifecycleError("Content exceeds parser input limit")
                if len(result) >= limit:
                    if strict:
                        continue
                    break
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        return bytes(result)


async def _single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


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
