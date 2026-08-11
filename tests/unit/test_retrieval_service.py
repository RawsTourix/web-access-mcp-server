from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime

import pytest

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import AuthorizationError, ErrorCategory
from web_access.application.common.hints import Warning, native_processing_unsupported
from web_access.application.common.results import LeafOutcome, OperationOutcome
from web_access.application.content.models import ContentInspection, ContentRef, NativeParseResult
from web_access.application.content.service import ContentParserTimeoutError
from web_access.application.retrieval.ports import (
    FetchCounters,
    RetrievalConnectionError,
    SafeFetchResponse,
)
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.core.config import RetrievalSettings
from web_access.core.time import SystemClock
from web_access.domain.content import (
    ContentFormat,
    ContentRepresentationKind,
    ParserAvailability,
)
from web_access.domain.retrieval import (
    RetrievalBatchRequest,
    RetrievalProcessingLevel,
    RetrievalRequestItem,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _context(*, scopes: frozenset[str] = frozenset({"retrieval:read"})) -> ExecutionContext:
    return ExecutionContext(
        operation_id="op_retrieval",
        principal=PrincipalContext("principal", scopes),
        clock=SystemClock(),
        cancellation=CancellationToken(),
    )


def _ref(
    content_id: str,
    representation: ContentRepresentationKind = ContentRepresentationKind.RAW,
) -> ContentRef:
    return ContentRef(
        content_id=content_id,
        media_type="text/plain",
        representation=representation,
        size_bytes=4,
        sha256="a" * 64,
        created_at=_NOW,
    )


class FakeFetcher:
    def __init__(
        self,
        *,
        statuses: dict[str, int] | None = None,
        failures: dict[str, Exception] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.statuses = statuses or {}
        self.failures = failures or {}
        self.delay = delay
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def fetch(self, context: ExecutionContext, url: str) -> SafeFetchResponse:
        del context
        self.calls.append(url)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            failure = self.failures.get(url)
            if failure is not None:
                raise failure
            counters = FetchCounters()

            async def body() -> AsyncIterator[bytes]:
                value = b"body"
                counters.wire_bytes += len(value)
                counters.entity_bytes += len(value)
                yield value

            return SafeFetchResponse(
                requested_url=url,
                final_url=url,
                http_status=self.statuses.get(url, 200),
                redirect_chain=(),
                content_encoding=None,
                declared_media_type="text/plain",
                source_filename="source.txt",
                body=body(),
                counters=counters,
            )
        finally:
            self.active -= 1


class FakeContentPipeline:
    def __init__(
        self,
        *,
        lose_ingest_result: bool = False,
        parse_failure: Exception | None = None,
        native_unsupported: bool = False,
    ) -> None:
        self.lose_ingest_result = lose_ingest_result
        self.parse_failure = parse_failure
        self.native_unsupported = native_unsupported
        self.ingested: list[bytes] = []
        self.inspected: list[str] = []
        self.parsed: list[str] = []
        self.browser_calls = 0
        self.advanced_processing_calls = 0
        self.job_calls = 0

    async def ingest(
        self,
        context: ExecutionContext,
        stream: AsyncIterable[bytes],
        *,
        representation_kind: ContentRepresentationKind,
        media_type: str | None = None,
        source_filename: str | None = None,
    ) -> ContentRef:
        del context, media_type, source_filename
        assert representation_kind is ContentRepresentationKind.RAW
        body = b"".join([chunk async for chunk in stream])
        self.ingested.append(body)
        if self.lose_ingest_result:
            raise RuntimeError("controlled response loss after resource creation")
        return _ref(f"cnt_{len(self.ingested):032x}")

    async def inspect(self, context: ExecutionContext, content_id: str) -> ContentInspection:
        del context
        self.inspected.append(content_id)
        return ContentInspection(
            size_bytes=4,
            sha256="a" * 64,
            declared_media_type="text/plain",
            detected_media_type="text/plain",
            detected_format=ContentFormat.TEXT,
            source_filename="source.txt",
            encoding="utf-8",
            parser_availability=ParserAvailability.AVAILABLE,
        )

    async def native_parse(self, context: ExecutionContext, content_id: str) -> NativeParseResult:
        del context
        self.parsed.append(content_id)
        if self.parse_failure is not None:
            raise self.parse_failure
        if self.native_unsupported:
            return NativeParseResult(
                source=_ref(content_id),
                reused=False,
                warnings=(
                    Warning(
                        code="native_processing_unsupported",
                        message="Формат не поддерживается L1 parsers.",
                    ),
                ),
                hints=(native_processing_unsupported(),),
            )
        return NativeParseResult(
            source=_ref(content_id),
            representations=(
                _ref(
                    f"cnt_{(100 + len(self.parsed)):032x}",
                    ContentRepresentationKind.TEXT,
                ),
            ),
            reused=False,
            parser_capability="text",
        )


def _service(
    fetcher: FakeFetcher, content: FakeContentPipeline, *, concurrency: int = 2
) -> RetrievalApplicationService:
    return RetrievalApplicationService(
        fetcher=fetcher,
        content=content,
        settings=RetrievalSettings(batch_concurrency=concurrency),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "inspections", "parses", "has_native"),
    [
        (RetrievalProcessingLevel.STORE_ONLY, 0, 0, False),
        (RetrievalProcessingLevel.INSPECT, 1, 0, False),
        (RetrievalProcessingLevel.NATIVE, 1, 1, True),
    ],
)
async def test_processing_levels_delegate_without_parser_logic(
    level: RetrievalProcessingLevel,
    inspections: int,
    parses: int,
    has_native: bool,
) -> None:
    fetcher = FakeFetcher()
    content = FakeContentPipeline()
    result = await _service(fetcher, content).fetch(
        _context(),
        RetrievalBatchRequest((RetrievalRequestItem("https://example.com/a"),), level),
    )

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data is not None
    item = result.data.items[0]
    assert item.data is not None
    assert item.data.raw_content.representation is ContentRepresentationKind.RAW
    assert (item.data.inspection is not None) is (inspections == 1)
    assert (item.data.native_content is not None) is has_native
    assert len(content.inspected) == inspections
    assert len(content.parsed) == parses
    assert content.browser_calls == 0
    assert content.advanced_processing_calls == 0
    assert content.job_calls == 0


@pytest.mark.asyncio
async def test_batch_preserves_duplicate_positions_isolates_failure_and_bounds_concurrency() -> (
    None
):
    duplicate = "https://example.com/duplicate"
    failed = "https://example.com/failed"
    fetcher = FakeFetcher(
        failures={failed: RetrievalConnectionError("network")},
        delay=0.01,
    )
    content = FakeContentPipeline()
    request = RetrievalBatchRequest(
        (
            RetrievalRequestItem(duplicate),
            RetrievalRequestItem(failed),
            RetrievalRequestItem(duplicate),
        ),
        RetrievalProcessingLevel.STORE_ONLY,
    )

    result = await _service(fetcher, content, concurrency=2).fetch(_context(), request)

    assert result.outcome is OperationOutcome.PARTIAL_SUCCESS
    assert result.data is not None
    assert [item.index for item in result.data.items] == [0, 1, 2]
    assert [item.outcome for item in result.data.items] == [
        LeafOutcome.SUCCEEDED,
        LeafOutcome.FAILED,
        LeafOutcome.SUCCEEDED,
    ]
    assert fetcher.calls.count(duplicate) == 2
    assert fetcher.calls.count(failed) == 1
    assert fetcher.max_active == 2


@pytest.mark.asyncio
async def test_non_success_http_status_keeps_body_metadata_and_raw_content() -> None:
    url = "https://example.com/missing"
    fetcher = FakeFetcher(statuses={url: 404})
    content = FakeContentPipeline()

    result = await _service(fetcher, content).fetch(
        _context(),
        RetrievalBatchRequest((RetrievalRequestItem(url),), RetrievalProcessingLevel.INSPECT),
    )

    assert result.outcome is OperationOutcome.FAILED
    assert result.error is not None
    assert result.error.code == "upstream_http_status"
    assert result.data is not None
    item = result.data.items[0]
    assert item.outcome is LeafOutcome.FAILED
    assert item.data is not None
    assert item.data.http_status == 404
    assert item.data.raw_content.content_id.startswith("cnt_")
    assert item.data.inspection is not None
    assert content.ingested == [b"body"]


@pytest.mark.asyncio
async def test_unsupported_native_processing_keeps_raw_as_success_with_trusted_hint() -> None:
    fetcher = FakeFetcher()
    content = FakeContentPipeline(native_unsupported=True)

    result = await _service(fetcher, content).fetch(
        _context(),
        RetrievalBatchRequest(
            (RetrievalRequestItem("https://example.com/unsupported"),),
            RetrievalProcessingLevel.NATIVE,
        ),
    )

    assert result.outcome is OperationOutcome.SUCCEEDED
    assert result.data is not None
    item = result.data.items[0]
    assert item.outcome is LeafOutcome.SUCCEEDED
    assert item.data is not None
    assert item.data.raw_content.content_id.startswith("cnt_")
    assert item.data.native_content is None
    assert item.data.available_representations == ()
    assert [warning.code for warning in item.warnings] == ["native_processing_unsupported"]
    assert [hint.code for hint in item.hints] == ["native_processing_unsupported"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_category"),
    [
        (
            RuntimeError("raw internal parser detail"),
            "native_processing_failed",
            ErrorCategory.INTERNAL,
        ),
        (ContentParserTimeoutError("raw timeout detail"), "parser_timeout", ErrorCategory.TIMEOUT),
    ],
)
async def test_native_failure_keeps_confirmed_raw_and_hides_exception_detail(
    failure: Exception,
    expected_code: str,
    expected_category: ErrorCategory,
) -> None:
    fetcher = FakeFetcher()
    content = FakeContentPipeline(parse_failure=failure)

    result = await _service(fetcher, content).fetch(
        _context(),
        RetrievalBatchRequest(
            (RetrievalRequestItem("https://example.com/document"),),
            RetrievalProcessingLevel.NATIVE,
        ),
    )

    assert result.outcome is OperationOutcome.FAILED
    assert result.data is not None
    item = result.data.items[0]
    assert item.outcome is LeafOutcome.FAILED
    assert item.data is not None
    assert item.data.raw_content.content_id.startswith("cnt_")
    assert item.data.inspection is not None
    assert item.error is not None
    assert item.error.code == expected_code
    assert item.error.category is expected_category
    assert "raw" not in item.error.message
    assert [warning.code for warning in item.warnings] == [expected_code]
    assert fetcher.calls == ["https://example.com/document"]
    assert len(content.ingested) == 1


@pytest.mark.asyncio
async def test_transport_failure_has_no_automatic_retry() -> None:
    url = "https://example.com/unavailable"
    fetcher = FakeFetcher(failures={url: RetrievalConnectionError("network")})
    content = FakeContentPipeline()

    result = await _service(fetcher, content).fetch(
        _context(), RetrievalBatchRequest((RetrievalRequestItem(url),))
    )

    assert result.outcome is OperationOutcome.FAILED
    assert result.error is not None
    assert result.error.category is ErrorCategory.UPSTREAM
    assert fetcher.calls == [url]
    assert content.ingested == []


@pytest.mark.asyncio
async def test_content_creation_response_loss_is_unknown_and_never_reacquired() -> None:
    url = "https://example.com/ambiguous"
    fetcher = FakeFetcher()
    content = FakeContentPipeline(lose_ingest_result=True)

    result = await _service(fetcher, content).fetch(
        _context(), RetrievalBatchRequest((RetrievalRequestItem(url),))
    )

    assert result.outcome is OperationOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.code == "retrieval_resource_outcome_unknown"
    assert result.error.retryable is False
    assert result.error.details == {"retrieval_phase": "content_staging"}
    assert fetcher.calls == [url]
    assert content.ingested == [b"body"]


@pytest.mark.asyncio
async def test_explicit_second_caller_operation_is_a_new_acquisition() -> None:
    url = "https://example.com/explicit-retry"
    fetcher = FakeFetcher()
    content = FakeContentPipeline()
    service = _service(fetcher, content)
    request = RetrievalBatchRequest((RetrievalRequestItem(url),))
    first_context = _context()
    second_context = ExecutionContext(
        operation_id="op_explicit_second",
        principal=first_context.principal,
        clock=first_context.clock,
        cancellation=CancellationToken(),
    )

    first = await service.fetch(first_context, request)
    second = await service.fetch(second_context, request)

    assert first.operation_id != second.operation_id
    assert first.outcome is second.outcome is OperationOutcome.SUCCEEDED
    assert fetcher.calls == [url, url]
    assert content.ingested == [b"body", b"body"]


@pytest.mark.asyncio
async def test_scope_is_checked_before_any_fetch() -> None:
    fetcher = FakeFetcher()
    content = FakeContentPipeline()
    with pytest.raises(AuthorizationError):
        await _service(fetcher, content).fetch(
            _context(scopes=frozenset()),
            RetrievalBatchRequest((RetrievalRequestItem("https://example.com"),)),
        )
    assert fetcher.calls == []
