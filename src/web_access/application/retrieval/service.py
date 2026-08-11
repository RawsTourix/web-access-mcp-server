"""Authorized, bounded Retrieval orchestration without parser implementation logic."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from pydantic import JsonValue

from web_access.application.common.auth import require_scope
from web_access.application.common.context import ExecutionContext, PrincipalContext
from web_access.application.common.errors import ErrorCategory, OperationError, PublicError
from web_access.application.common.hints import Warning
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
    aggregate_batch_outcome,
)
from web_access.application.content.models import ContentInspection, ContentRef
from web_access.application.content.service import ContentParserTimeoutError, ContentProcessingError
from web_access.application.retrieval.models import RetrievalBatchResult, RetrievalItemResult
from web_access.application.retrieval.ports import (
    DecompressionLimitExceeded,
    ResponseTooLarge,
    RetrievalConnectionError,
    RetrievalContentPipeline,
    RetrievalPolicyError,
    SafeHttpFetcher,
    TooManyRedirects,
    UnsupportedContentEncoding,
)
from web_access.application.retrieval.retry import RetrievalPhaseTracker
from web_access.core.config import RetrievalSettings
from web_access.core.time import Deadline
from web_access.domain.content import ContentRepresentationKind
from web_access.domain.retrieval import (
    RetrievalBatchRequest,
    RetrievalExecutionPhase,
    RetrievalProcessingLevel,
    RetrievalRequestItem,
    RetrievedResource,
)


class RetrievalApplicationService:
    def __init__(
        self,
        *,
        fetcher: SafeHttpFetcher,
        content: RetrievalContentPipeline,
        settings: RetrievalSettings,
    ) -> None:
        self._fetcher = fetcher
        self._content = content
        self._settings = settings

    async def fetch(
        self, context: ExecutionContext, request: RetrievalBatchRequest
    ) -> OperationResult[RetrievalBatchResult]:
        require_scope(context.principal, "retrieval:read")
        context = replace(
            context,
            principal=PrincipalContext(
                context.principal.principal_id,
                context.principal.scopes | frozenset({"content:read", "content:write"}),
            ),
        )
        if context.deadline is None:
            context = replace(
                context,
                deadline=Deadline.after(context.clock, self._settings.operation_timeout_seconds),
            )
        semaphore = asyncio.Semaphore(self._settings.batch_concurrency)

        async def run(
            index: int, item: RetrievalRequestItem
        ) -> BatchItemResult[RetrievalItemResult]:
            async with semaphore:
                if context.cancellation.requested:
                    return _error_item(
                        index,
                        LeafOutcome.CANCELLED,
                        ErrorCategory.CANCELLED,
                        "retrieval_cancelled",
                        "Retrieval item отменён до отправки запроса.",
                    )
                return await self._fetch_item(context, index, item, request.processing_level)

        items = tuple(
            await asyncio.gather(*(run(index, item) for index, item in enumerate(request.items)))
        )
        outcome = aggregate_batch_outcome([item.outcome for item in items])
        error = None
        if outcome not in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
            error = _aggregate_error(outcome, items)
        return OperationResult(
            operation_id=context.operation_id,
            outcome=outcome,
            data=RetrievalBatchResult(items=items),
            error=error,
        )

    async def _fetch_item(
        self,
        context: ExecutionContext,
        index: int,
        item: RetrievalRequestItem,
        processing_level: RetrievalProcessingLevel,
    ) -> BatchItemResult[RetrievalItemResult]:
        phase = RetrievalPhaseTracker()
        try:
            phase.advance(RetrievalExecutionPhase.VALIDATED)
            phase.advance(RetrievalExecutionPhase.DNS_RESOLVING)
            phase.advance(RetrievalExecutionPhase.CONNECTING)
            # The aiohttp dispatch boundary is deliberately treated as ambiguous:
            # connection/request failures after this point never trigger a blind retry.
            phase.advance(RetrievalExecutionPhase.DISPATCH_POSSIBLE)
            response = await self._fetcher.fetch(context, item.url)
            phase.advance(RetrievalExecutionPhase.RESPONSE_HEADERS)
            phase.advance(RetrievalExecutionPhase.BODY_STREAMING)
            phase.advance(RetrievalExecutionPhase.CONTENT_CREATING)
            phase.advance(RetrievalExecutionPhase.CONTENT_STAGING)
            raw = await self._content.ingest(
                context,
                response.body,
                representation_kind=ContentRepresentationKind.RAW,
                media_type=response.declared_media_type,
                source_filename=response.source_filename,
            )
            phase.advance(RetrievalExecutionPhase.CONTENT_FINALIZED)
            inspection = None
            native = None
            representations = ()
            warnings = ()
            hints = ()
            processing_code = "content_inspection_failed"
            try:
                if processing_level is not RetrievalProcessingLevel.STORE_ONLY:
                    phase.advance(RetrievalExecutionPhase.PROCESSING)
                    inspection = await self._content.inspect(context, raw.content_id)
                if processing_level is RetrievalProcessingLevel.NATIVE:
                    processing_code = "native_processing_failed"
                    parsed = await self._content.native_parse(context, raw.content_id)
                    representations = parsed.representations
                    native = representations[0] if representations else None
                    warnings = parsed.warnings
                    hints = parsed.hints
            except Exception as error:
                metadata = response.metadata()
                phase.advance(RetrievalExecutionPhase.TERMINAL)
                code = processing_code
                category = ErrorCategory.INTERNAL
                message = "Запрошенную нативную обработку Content завершить не удалось."
                if isinstance(error, ContentParserTimeoutError):
                    code = error.code
                    category = ErrorCategory.TIMEOUT
                    message = "L1 Native Parser не завершил обработку вовремя."
                elif isinstance(error, ContentProcessingError):
                    code = error.code
                return BatchItemResult(
                    index=index,
                    outcome=LeafOutcome.FAILED,
                    data=_retrieval_data(
                        metadata,
                        raw,
                        inspection=inspection,
                        native_content=native,
                        representations=representations,
                    ),
                    error=OperationError(category=category, code=code, message=message),
                    warnings=(Warning(code=code, message=message),),
                )

            metadata = response.metadata()
            data = _retrieval_data(
                metadata,
                raw,
                inspection=inspection,
                native_content=native,
                representations=representations,
            )
            phase.advance(RetrievalExecutionPhase.TERMINAL)
            if 200 <= metadata.http_status < 300:
                return BatchItemResult(
                    index=index,
                    outcome=LeafOutcome.SUCCEEDED,
                    data=data,
                    warnings=warnings,
                    hints=hints,
                )
            error = OperationError(
                category=ErrorCategory.UPSTREAM,
                code="upstream_http_status",
                message="Upstream-сервер вернул неуспешный HTTP-статус.",
                retryable=metadata.http_status >= 500,
                details={"http_status": metadata.http_status},
            )
            return BatchItemResult(
                index=index,
                outcome=LeafOutcome.FAILED,
                data=data,
                error=error,
                warnings=warnings,
                hints=hints,
            )
        except RetrievalPolicyError as error:
            return _error_item(
                index,
                LeafOutcome.REJECTED,
                ErrorCategory.POLICY,
                getattr(error, "code", "retrieval_url_blocked"),
                "Запрошенный адрес Retrieval запрещён политикой безопасности.",
                details={"retrieval_phase": phase.phase_value},
            )
        except TooManyRedirects:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.UPSTREAM,
                "too_many_redirects",
                "Превышен лимит upstream-перенаправлений.",
                details={"retrieval_phase": phase.phase_value},
            )
        except ResponseTooLarge:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.CAPACITY,
                "response_too_large",
                "Полученный ответ превысил допустимый размер.",
                details={"retrieval_phase": phase.phase_value},
            )
        except DecompressionLimitExceeded:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.CAPACITY,
                "decompression_limit",
                "Полученный ответ превысил лимит декомпрессии.",
                details={"retrieval_phase": phase.phase_value},
            )
        except UnsupportedContentEncoding:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.UNSUPPORTED,
                "unsupported_content_encoding",
                "Upstream Content-Encoding не поддерживается.",
                details={"retrieval_phase": phase.phase_value},
            )
        except TimeoutError:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.TIMEOUT,
                "retrieval_timeout",
                "Время выполнения Retrieval истекло.",
                details={"retrieval_phase": phase.phase_value},
            )
        except RetrievalConnectionError:
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.UPSTREAM,
                "retrieval_transport_error",
                "Получить upstream-ответ не удалось.",
                details={"retrieval_phase": phase.phase_value},
            )
        except Exception:
            if phase.resource_creation_possible:
                return _error_item(
                    index,
                    LeafOutcome.UNKNOWN,
                    ErrorCategory.UNKNOWN_OUTCOME,
                    "retrieval_resource_outcome_unknown",
                    "Retrieval мог создать Content, но результат создания не подтверждён.",
                    details={"retrieval_phase": phase.phase_value},
                )
            return _error_item(
                index,
                LeafOutcome.FAILED,
                ErrorCategory.INTERNAL,
                "retrieval_internal_error",
                "Завершить Retrieval item не удалось.",
                details={"retrieval_phase": phase.phase_value},
            )


def _retrieval_data(
    metadata: RetrievedResource,
    raw: ContentRef,
    *,
    inspection: ContentInspection | None,
    native_content: ContentRef | None,
    representations: tuple[ContentRef, ...],
) -> RetrievalItemResult:
    return RetrievalItemResult(
        requested_url=metadata.requested_url,
        final_url=metadata.final_url,
        http_status=metadata.http_status,
        redirect_chain=metadata.redirect_chain,
        wire_bytes=metadata.wire_bytes,
        entity_bytes=metadata.entity_bytes,
        content_encoding=metadata.content_encoding,
        raw_content=raw,
        inspection=inspection,
        native_content=native_content,
        available_representations=representations,
    )


def _error_item(
    index: int,
    outcome: LeafOutcome,
    category: ErrorCategory,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, JsonValue] | None = None,
) -> BatchItemResult[RetrievalItemResult]:
    return BatchItemResult(
        index=index,
        outcome=outcome,
        error=OperationError(
            category=category,
            code=code,
            message=message,
            retryable=retryable,
            details=details,
        ),
    )


def _aggregate_error(
    outcome: OperationOutcome,
    items: tuple[BatchItemResult[RetrievalItemResult], ...],
) -> PublicError:
    candidates = list(items)
    if outcome is OperationOutcome.UNKNOWN:
        candidates = [item for item in candidates if item.outcome is LeafOutcome.UNKNOWN]
    elif outcome is OperationOutcome.REJECTED:
        candidates = [item for item in candidates if item.outcome is LeafOutcome.REJECTED]
    elif outcome is OperationOutcome.CANCELLED:
        candidates = [item for item in candidates if item.outcome is LeafOutcome.CANCELLED]
    for candidate in candidates:
        if candidate.error is not None:
            return candidate.error
    raise RuntimeError("Retrieval aggregate candidate has no error")
