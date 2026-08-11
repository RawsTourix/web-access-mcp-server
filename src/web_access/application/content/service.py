"""Content lifecycle orchestration over application-owned ports."""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
from collections.abc import AsyncIterable, AsyncIterator

from web_access.application.common.auth import require_owner, require_scope
from web_access.application.common.content_store import ContentStore, StagedBlob
from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import AuthorizationError, ErrorCategory, OperationError
from web_access.application.common.hints import Warning, native_processing_unsupported
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
    aggregate_batch_outcome,
)
from web_access.application.content.models import (
    ContentInspectBatchResult,
    ContentInspection,
    ContentInspectResult,
    ContentMetadata,
    ContentNativeParseBatchResult,
    ContentProvenance,
    ContentReadResult,
    ContentRef,
    ContentRepresentationsResult,
    ContentRepresentationSummary,
    ContentRetention,
    NativeParseResult,
    ParsedRepresentation,
    ParserDescriptor,
)
from web_access.application.content.ports import (
    AuthorizedContentStream,
    ContentCursorClaims,
    ContentCursorCodec,
    ContentIdentifier,
    ContentRecord,
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
    code = "content_processing_failed"


class ContentNotFoundError(ContentLifecycleError):
    code = "content_not_found"


class ContentUnavailableError(ContentLifecycleError):
    code = "content_unavailable"


class ContentProcessingError(ContentLifecycleError):
    code = "native_processing_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(message)


class ContentParserTimeoutError(ContentProcessingError):
    code = "parser_timeout"


class ContentCursorError(ValueError):
    code = "invalid_content_cursor"


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
        cursor_codec: ContentCursorCodec | None = None,
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
        self._cursor_codec = cursor_codec
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
        require_scope(context.principal, "content:read")
        identifier = self._identifier
        if identifier is None:
            raise ContentLifecycleError("Content identifier is not configured")
        typed_id = _typed_content_id(content_id)
        async with self._uow_factory() as uow:
            record = await uow.contents.get(typed_id)
        if record is None:
            raise ContentNotFoundError("Content was not found")
        require_owner(context.principal, record.content.owner_principal_id)
        if record.content.state is not ContentState.AVAILABLE or record.storage_key is None:
            raise ContentUnavailableError("Content is not available")
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
        require_scope(context.principal, "content:write")
        require_scope(context.principal, "content:read")
        registry = self._parser_registry
        executor = self._parser_executor
        if registry is None or executor is None:
            raise ContentLifecycleError("native parser runtime is not configured")
        typed_id = _typed_content_id(content_id)
        inspection = await self.inspect(context, content_id)
        async with self._uow_factory() as uow:
            record = await uow.contents.get(typed_id)
        if (
            record is None
            or record.content.state is not ContentState.AVAILABLE
            or record.storage_key is None
        ):
            raise ContentUnavailableError("Content is not available")
        require_owner(context.principal, record.content.owner_principal_id)
        source_ref = _content_ref(record.content)
        parser = registry.select(inspection)
        if parser is None:
            return NativeParseResult(
                source=source_ref,
                reused=False,
                warnings=(
                    Warning(
                        code="native_processing_unsupported",
                        message=(
                            "Обнаруженный формат не поддерживается зарегистрированными L1 parsers."
                        ),
                    ),
                ),
                hints=(native_processing_unsupported(),),
            )
        data = await self._read_bounded(record.storage_key, self._parser_input_bytes)
        try:
            output = await executor.execute(parser, record.content, inspection, data)
        except Exception as error:
            source_code = getattr(error, "code", None)
            if source_code == "parser_child_timeout" or isinstance(error, TimeoutError):
                raise ContentParserTimeoutError("Native parser timed out") from error
            public_code = (
                source_code
                if source_code
                in {
                    "encrypted_content",
                    "malformed_pdf",
                    "native_parse_failed",
                    "parser_depth_limit",
                    "parser_input_limit",
                    "parser_output_limit",
                }
                else None
            )
            raise ContentProcessingError("Native parser failed", code=public_code) from error
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

    async def metadata(self, context: ExecutionContext, content_id: str) -> ContentMetadata:
        record, targets = await self._load_authorized(context, content_id)
        return ContentMetadata(
            content=_content_ref(record.content),
            state=record.content.state,
            representation_kind=record.content.representation_kind,
            media_type=record.content.media_type,
            detected_format=record.content.detected_format,
            source_filename=record.content.source_filename,
            inspection=record.inspection,
            provenance=_provenance(record.content),
            available_representations=tuple(_content_ref(item.content) for item in targets),
            retention=ContentRetention(expires_at=record.content.expires_at),
        )

    async def inspect_many(
        self, context: ExecutionContext, content_ids: tuple[str, ...]
    ) -> OperationResult[ContentInspectBatchResult]:
        require_scope(context.principal, "content:read")
        items: list[BatchItemResult[ContentInspectResult]] = []
        for index, content_id in enumerate(content_ids):
            try:
                inspection = await self.inspect(context, content_id)
                metadata = await self.metadata(context, content_id)
                items.append(
                    BatchItemResult(
                        index=index,
                        outcome=LeafOutcome.SUCCEEDED,
                        data=ContentInspectResult(content=metadata.content, inspection=inspection),
                    )
                )
            except Exception as error:
                items.append(_content_batch_error(index, error))
        return _content_batch_result(
            context.operation_id, ContentInspectBatchResult(items=tuple(items)), items
        )

    async def native_parse_many(
        self, context: ExecutionContext, content_ids: tuple[str, ...]
    ) -> OperationResult[ContentNativeParseBatchResult]:
        require_scope(context.principal, "content:read")
        require_scope(context.principal, "content:write")
        items: list[BatchItemResult[NativeParseResult]] = []
        for index, content_id in enumerate(content_ids):
            try:
                items.append(
                    BatchItemResult(
                        index=index,
                        outcome=LeafOutcome.SUCCEEDED,
                        data=await self.native_parse(context, content_id),
                    )
                )
            except Exception as error:
                items.append(_content_batch_error(index, error))
        return _content_batch_result(
            context.operation_id, ContentNativeParseBatchResult(items=tuple(items)), items
        )

    async def representations(
        self, context: ExecutionContext, content_id: str
    ) -> ContentRepresentationsResult:
        record, targets = await self._load_authorized(context, content_id)
        summaries = []
        for target in targets:
            provenance = _provenance(target.content)
            if provenance is None:
                raise ContentLifecycleError("derived Content provenance is missing")
            summaries.append(
                ContentRepresentationSummary(
                    content=_content_ref(target.content),
                    relation_type=ContentRelationType.DERIVED_FROM,
                    representation_kind=target.content.representation_kind,
                    provenance=provenance,
                )
            )
        return ContentRepresentationsResult(
            source=_content_ref(record.content), representations=tuple(summaries)
        )

    async def read(
        self,
        context: ExecutionContext,
        content_id: str,
        *,
        max_chars: int = 12000,
        cursor: str | None = None,
    ) -> ContentReadResult:
        if not 1 <= max_chars <= 30000:
            raise ValueError("max_chars must be between 1 and 30000")
        record, targets = await self._load_authorized(context, content_id)
        representations = tuple(_content_ref(item.content) for item in targets)
        reference = _content_ref(record.content)
        if record.content.representation_kind not in {
            ContentRepresentationKind.TEXT,
            ContentRepresentationKind.MARKDOWN,
            ContentRepresentationKind.STRUCTURED,
        }:
            if cursor is not None:
                raise ContentCursorError("Content cursor cannot be used with binary Content")
            return ContentReadResult(
                content=reference,
                returned_chars=0,
                inspection=record.inspection,
                available_representations=representations,
            )
        codec = self._cursor_codec
        if codec is None:
            raise ContentLifecycleError("Content cursor codec is not configured")
        offset = 0
        if cursor is not None:
            try:
                claims = codec.decode(cursor)
            except ValueError as error:
                raise ContentCursorError("Content cursor is malformed or tampered") from error
            if (
                claims.owner_principal_id != context.principal.principal_id
                or claims.content_id != record.content.content_id
                or claims.content_revision != record.content.revision
            ):
                raise ContentCursorError("Content cursor does not match this resource revision")
            offset = claims.byte_offset
        if record.storage_key is None:
            raise ContentLifecycleError("Content storage metadata is missing")
        try:
            text_value, next_offset = await self._read_utf8_chunk(
                record.storage_key, offset=offset, max_chars=max_chars
            )
        except UnicodeDecodeError as error:
            raise ContentLifecycleError("text Content is not valid UTF-8") from error
        next_cursor = None
        if next_offset is not None:
            next_cursor = codec.encode(
                ContentCursorClaims(
                    owner_principal_id=context.principal.principal_id,
                    content_id=record.content.content_id,
                    content_revision=record.content.revision,
                    byte_offset=next_offset,
                )
            )
        return ContentReadResult(
            content=reference,
            text=text_value,
            returned_chars=len(text_value),
            next_cursor=next_cursor,
            inspection=record.inspection,
            available_representations=representations,
        )

    async def open_data(
        self, context: ExecutionContext, content_id: str
    ) -> AuthorizedContentStream:
        record, _ = await self._load_authorized(context, content_id)
        if record.storage_key is None:
            raise ContentLifecycleError("Content storage metadata is missing")
        observed = await self._store.stat(record.storage_key)
        if (
            observed is None
            or observed.sha256 != record.content.sha256
            or observed.size != record.content.size_bytes
        ):
            raise ContentLifecycleError("Content storage integrity verification failed")
        return AuthorizedContentStream(
            content=_content_ref(record.content),
            source_filename=record.content.source_filename,
            stream=self._store.open_stream(record.storage_key),
        )

    async def _load_authorized(
        self, context: ExecutionContext, content_id: str
    ) -> tuple[ContentRecord, tuple[ContentRecord, ...]]:
        require_scope(context.principal, "content:read")
        typed_id = _typed_content_id(content_id)
        async with self._uow_factory() as uow:
            record = await uow.contents.get(typed_id)
            if record is None:
                raise ContentNotFoundError("Content was not found")
            require_owner(context.principal, record.content.owner_principal_id)
            if (
                record.content.state is not ContentState.AVAILABLE
                or record.storage_key is None
                or (
                    record.content.expires_at is not None
                    and record.content.expires_at <= context.clock.utc_now()
                )
            ):
                raise ContentUnavailableError("Content is not available")
            relations = await uow.relations.for_source(typed_id, limit=32)
            available: list[ContentRecord] = []
            for relation in relations:
                target = await uow.contents.get(relation.target_content_id)
                if (
                    target is not None
                    and target.content.owner_principal_id == context.principal.principal_id
                    and target.content.state is ContentState.AVAILABLE
                    and (
                        target.content.expires_at is None
                        or target.content.expires_at > context.clock.utc_now()
                    )
                ):
                    available.append(target)
        return record, tuple(available)

    async def _read_utf8_chunk(
        self, storage_key: str, *, offset: int, max_chars: int
    ) -> tuple[str, int | None]:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        parts: list[str] = []
        character_count = 0
        skipped = 0
        stream = self._store.open_stream(storage_key)
        exceeded = False
        try:
            async for chunk in stream:
                if skipped < offset:
                    consumed = min(len(chunk), offset - skipped)
                    skipped += consumed
                    chunk = chunk[consumed:]
                    if not chunk:
                        continue
                decoded = decoder.decode(chunk, final=False)
                parts.append(decoded)
                character_count += len(decoded)
                if character_count > max_chars:
                    exceeded = True
                    break
            if skipped < offset:
                raise ContentCursorError("Content cursor offset exceeds the resource")
            if not exceeded:
                parts.append(decoder.decode(b"", final=True))
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        value = "".join(parts)
        if len(value) <= max_chars:
            return value, None
        bounded = value[:max_chars]
        returned_bytes = len(bounded.encode("utf-8"))
        return bounded, offset + returned_bytes

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


def _provenance(content: ContentObject) -> ContentProvenance | None:
    if content.source_content_id is None:
        return None
    if any(
        value is None
        for value in (
            content.producer_capability,
            content.producer_revision,
            content.representation_schema_revision,
            content.processing_profile_revision,
        )
    ):
        raise ContentLifecycleError("derived Content provenance is incomplete")
    return ContentProvenance(
        source_content_id=str(content.source_content_id),
        producer_capability=content.producer_capability or "",
        producer_revision=content.producer_revision or "",
        representation_schema_revision=content.representation_schema_revision or "",
        processing_profile_revision=content.processing_profile_revision or "",
    )


def _typed_content_id(value: str) -> ContentId:
    try:
        return ContentId(value)
    except ValueError as error:
        raise ContentNotFoundError("Content was not found") from error


def _content_batch_error(index: int, error: Exception) -> BatchItemResult:
    if isinstance(error, AuthorizationError):
        category = ErrorCategory.PERMISSION
        code = error.code.value
        outcome = LeafOutcome.REJECTED
        message = str(error)
    elif isinstance(error, ContentNotFoundError):
        category = ErrorCategory.NOT_FOUND
        code = error.code
        outcome = LeafOutcome.FAILED
        message = "Content was not found."
    elif isinstance(error, ContentUnavailableError):
        category = ErrorCategory.CONFLICT
        code = error.code
        outcome = LeafOutcome.FAILED
        message = "Content is not available."
    else:
        category = ErrorCategory.INTERNAL
        code = getattr(error, "code", "content_processing_failed")
        outcome = LeafOutcome.FAILED
        message = "Content processing failed."
    return BatchItemResult(
        index=index,
        outcome=outcome,
        error=OperationError(category=category, code=code, message=message),
    )


def _content_batch_result(
    operation_id: str,
    data: ContentInspectBatchResult | ContentNativeParseBatchResult,
    items: list[BatchItemResult],
) -> OperationResult:
    outcome = aggregate_batch_outcome([item.outcome for item in items])
    primary = None
    if outcome not in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
        primary = next(item.error for item in items if item.error is not None)
    return OperationResult(operation_id=operation_id, outcome=outcome, data=data, error=primary)
