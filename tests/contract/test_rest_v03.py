from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from web_access.application.common.context import ExecutionContext
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
)
from web_access.application.content.models import (
    ContentInspectBatchResult,
    ContentInspection,
    ContentInspectResult,
    ContentMetadata,
    ContentNativeParseBatchResult,
    ContentRef,
    ContentRepresentationsResult,
    ContentRetention,
    NativeParseResult,
)
from web_access.application.content.ports import AuthorizedContentStream
from web_access.application.content.service import ContentApplicationService
from web_access.application.retrieval.models import RetrievalBatchResult, RetrievalItemResult
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.bootstrap.app import create_control_plane
from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    Environment,
    PrincipalSettings,
    Settings,
)
from web_access.domain.content import (
    ContentFormat,
    ContentRepresentationKind,
    ContentState,
    ParserAvailability,
)
from web_access.domain.retrieval import RetrievalBatchRequest, RetrievalProcessingLevel

FULL_TOKEN = "f" * 32
READ_TOKEN = "r" * 32
CONTENT_ID = "cnt_0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app=AppSettings(environment=Environment.TEST, mandatory_dependencies=frozenset()),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="full-owner",
                    tokens=(SecretStr(FULL_TOKEN),),
                    scopes=frozenset({"retrieval:read", "content:read", "content:write"}),
                ),
                PrincipalSettings(
                    principal_id="read-owner",
                    tokens=(SecretStr(READ_TOKEN),),
                    scopes=frozenset({"content:read"}),
                ),
            )
        ),
        content_store=ContentStoreSettings(root=tmp_path),
    )


def _ref() -> ContentRef:
    return ContentRef(
        content_id=CONTENT_ID,
        media_type="text/html",
        representation=ContentRepresentationKind.RAW,
        size_bytes=4,
        sha256="a" * 64,
        created_at=NOW,
    )


def _inspection() -> ContentInspection:
    return ContentInspection(
        size_bytes=4,
        sha256="a" * 64,
        declared_media_type="text/html",
        detected_media_type="text/html",
        detected_format=ContentFormat.HTML,
        parser_availability=ParserAvailability.AVAILABLE,
    )


class _FakeRetrieval:
    context: ExecutionContext | None = None
    request: RetrievalBatchRequest | None = None

    async def fetch(
        self, context: ExecutionContext, request: RetrievalBatchRequest
    ) -> OperationResult[RetrievalBatchResult]:
        self.context = context
        self.request = request
        item = BatchItemResult(
            index=0,
            outcome=LeafOutcome.SUCCEEDED,
            data=RetrievalItemResult(
                requested_url=request.items[0].url,
                final_url=request.items[0].url,
                http_status=200,
                wire_bytes=4,
                entity_bytes=4,
                raw_content=_ref(),
                inspection=_inspection(),
            ),
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=RetrievalBatchResult(items=(item,)),
        )


class _FakeContent:
    parse_context: ExecutionContext | None = None

    async def metadata(self, context: ExecutionContext, content_id: str) -> ContentMetadata:
        del context
        assert content_id == CONTENT_ID
        return ContentMetadata(
            content=_ref(),
            state=ContentState.AVAILABLE,
            representation_kind=ContentRepresentationKind.RAW,
            media_type="text/html",
            detected_format=ContentFormat.HTML,
            source_filename="unsafe\r\nname.html",
            inspection=_inspection(),
            retention=ContentRetention(),
        )

    async def representations(
        self, context: ExecutionContext, content_id: str
    ) -> ContentRepresentationsResult:
        del context
        assert content_id == CONTENT_ID
        return ContentRepresentationsResult(source=_ref())

    async def inspect_many(
        self, context: ExecutionContext, content_ids: tuple[str, ...]
    ) -> OperationResult[ContentInspectBatchResult]:
        assert content_ids == (CONTENT_ID,)
        item = BatchItemResult(
            index=0,
            outcome=LeafOutcome.SUCCEEDED,
            data=ContentInspectResult(content=_ref(), inspection=_inspection()),
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=ContentInspectBatchResult(items=(item,)),
        )

    async def native_parse_many(
        self, context: ExecutionContext, content_ids: tuple[str, ...]
    ) -> OperationResult[ContentNativeParseBatchResult]:
        self.parse_context = context
        assert content_ids == (CONTENT_ID,)
        parsed = NativeParseResult(source=_ref(), reused=True, parser_capability="html")
        item = BatchItemResult(index=0, outcome=LeafOutcome.SUCCEEDED, data=parsed)
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=ContentNativeParseBatchResult(items=(item,)),
        )

    async def open_data(
        self, context: ExecutionContext, content_id: str
    ) -> AuthorizedContentStream:
        del context
        assert content_id == CONTENT_ID

        async def body() -> AsyncIterator[bytes]:
            yield b"html"

        return AuthorizedContentStream(
            content=_ref(), source_filename="unsafe\r\nname.html", stream=body()
        )


@pytest.mark.asyncio
async def test_v03_rest_facade_scopes_results_and_safe_streaming(tmp_path: Path) -> None:
    retrieval = _FakeRetrieval()
    content = _FakeContent()
    app = create_control_plane(_settings(tmp_path))
    full = {"Authorization": f"Bearer {FULL_TOKEN}"}
    read = {"Authorization": f"Bearer {READ_TOKEN}"}
    async with app.router.lifespan_context(app):
        app.state.container = replace(
            app.state.container,
            retrieval=cast(RetrievalApplicationService, retrieval),
            content=cast(ContentApplicationService, content),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            fetch = await client.post(
                "/api/v1/retrieval/fetch",
                headers=full,
                json={"items": [{"url": "https://example.test/doc"}]},
            )
            fetch_denied = await client.post(
                "/api/v1/retrieval/fetch",
                headers=read,
                json={"items": [{"url": "https://example.test/doc"}]},
            )
            metadata = await client.get(f"/api/v1/content/{CONTENT_ID}", headers=read)
            representations = await client.get(
                f"/api/v1/content/{CONTENT_ID}/representations", headers=read
            )
            inspect = await client.post(
                "/api/v1/content/inspect", headers=read, json={"content_ids": [CONTENT_ID]}
            )
            parse_denied = await client.post(
                "/api/v1/content/native-parse",
                headers=read,
                json={"content_ids": [CONTENT_ID]},
            )
            parsed = await client.post(
                "/api/v1/content/native-parse",
                headers=full,
                json={"content_ids": [CONTENT_ID]},
            )
            data = await client.get(f"/api/v1/content/{CONTENT_ID}/data", headers=read)
            ranged = await client.get(
                f"/api/v1/content/{CONTENT_ID}/data",
                headers={**read, "Range": "bytes=0-1"},
            )

    assert fetch.status_code == 200
    assert fetch.json()["data"]["items"][0]["data"]["raw_content"]["content_id"] == CONTENT_ID
    assert retrieval.request is not None
    assert retrieval.request.processing_level is RetrievalProcessingLevel.NATIVE
    assert fetch_denied.status_code == 403
    assert metadata.status_code == 200
    assert metadata.json()["data"]["state"] == "available"
    assert not {"storage_key", "staging_key", "path", "id"}.intersection(metadata.json()["data"])
    assert representations.status_code == 200
    assert inspect.status_code == 200
    assert parse_denied.status_code == 403
    assert parsed.status_code == 200
    assert content.parse_context is not None
    assert {"content:read", "content:write"}.issubset(content.parse_context.principal.scopes)
    assert data.status_code == 200 and data.content == b"html"
    assert data.headers["content-type"] == "application/octet-stream"
    assert data.headers["x-content-type-options"] == "nosniff"
    assert "\r" not in data.headers["content-disposition"]
    assert "\n" not in data.headers["content-disposition"]
    assert data.headers["content-disposition"].startswith("attachment;")
    assert ranged.status_code == 416
    assert ranged.headers["content-range"] == "bytes */4"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/retrieval/fetch", {"items": [{"url": "ftp://example.test"}]}),
        ("/api/v1/retrieval/fetch", {"items": [{"url": "https://example.test", "method": "GET"}]}),
        ("/api/v1/content/inspect", {"content_ids": [CONTENT_ID, CONTENT_ID]}),
        ("/api/v1/content/native-parse", {"content_ids": [CONTENT_ID], "parser": "pypdf"}),
    ],
)
async def test_v03_rest_rejects_non_contract_inputs(
    tmp_path: Path, path: str, payload: dict[str, object]
) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                path, headers={"Authorization": f"Bearer {FULL_TOKEN}"}, json=payload
            )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
