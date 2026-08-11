from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_access_token
from pydantic import SecretStr

from web_access.application.common.context import ExecutionContext
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
    RetryClass,
)
from web_access.application.content.models import (
    ContentInspection,
    ContentNativeParseBatchResult,
    ContentReadResult,
    ContentRef,
    NativeParseResult,
)
from web_access.application.content.service import ContentApplicationService
from web_access.application.retrieval.models import RetrievalBatchResult, RetrievalItemResult
from web_access.application.retrieval.service import RetrievalApplicationService
from web_access.application.search.models import (
    CacheMetadata,
    PaginationMetadata,
    SearchBatchRequest,
    SearchBatchResult,
    SearchQueryData,
)
from web_access.application.search.service import SearchApplicationService
from web_access.bootstrap.app import assemble_control_plane, create_control_plane
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
    ParserAvailability,
)
from web_access.domain.retrieval import RetrievalBatchRequest, RetrievalProcessingLevel
from web_access.domain.search import SearchProviderId, SearchResultItem
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.mcp.retry import trusted_retry_descriptor
from web_access.transport.mcp.server import create_mcp_server

TOKEN = "m" * 32
NO_SCOPE_TOKEN = "n" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app=AppSettings(environment=Environment.TEST, mandatory_dependencies=frozenset()),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="mcp-agent",
                    tokens=(SecretStr(TOKEN),),
                    scopes=frozenset(
                        {
                            "admin:read",
                            "search:read",
                            "retrieval:read",
                            "content:read",
                            "content:write",
                        }
                    ),
                ),
                PrincipalSettings(
                    principal_id="mcp-limited-agent",
                    tokens=(SecretStr(NO_SCOPE_TOKEN),),
                    scopes=frozenset({"content:read"}),
                ),
            )
        ),
        content_store=ContentStoreSettings(root=tmp_path),
    )


def _client_factory(app):
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    return factory


def _client(app, token: str | None) -> Client:
    transport = StreamableHttpTransport(
        "http://localhost/mcp/",
        auth=token,
        httpx_client_factory=_client_factory(app),
    )
    return Client(transport)


@pytest.mark.asyncio
async def test_actual_mcp_client_auth_and_exact_production_catalog(tmp_path: Path) -> None:
    for token in (None, "invalid-credential"):
        rejected_app = create_control_plane(_settings(tmp_path / (token or "missing")))
        with pytest.raises(ExceptionGroup) as captured:
            async with rejected_app.router.lifespan_context(rejected_app):
                async with _client(rejected_app, token):
                    pytest.fail("unauthorized MCP initialization must not succeed")
        assert [error.response.status_code for error in _http_errors(captured.value)] == [401]

    app = create_control_plane(_settings(tmp_path / "authorized"))
    async with app.router.lifespan_context(app):
        async with _client(app, TOKEN) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == [
                "web_search",
                "web_fetch",
                "content_get",
                "content_parse",
            ]
            tool = tools[0]
            assert tool.description is not None
            assert "не читает содержимое" in tool.description
            assert "Yandex" in tool.description
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.idempotentHint is True
            assert tool.annotations.openWorldHint is True
            schema = tool.inputSchema
            assert schema["additionalProperties"] is False
            assert schema["required"] == ["queries"]
            assert set(schema["properties"]) == {
                "queries",
                "provider",
                "page",
                "limit",
                "language",
                "region",
                "safe_search",
                "time_range",
            }
            queries = schema["properties"]["queries"]
            assert (queries["minItems"], queries["maxItems"]) == (1, 8)
            assert (queries["items"]["minLength"], queries["items"]["maxLength"]) == (
                1,
                2048,
            )
            assert schema["properties"]["provider"]["enum"] == [
                "default",
                "searxng",
                "yandex",
            ]
            assert schema["properties"]["provider"]["default"] == "default"
            assert (
                "не переключает provider скрыто" in schema["properties"]["provider"]["description"]
            )
            assert (
                schema["properties"]["page"]["minimum"],
                schema["properties"]["page"]["maximum"],
            ) == (1, 100)
            assert (
                schema["properties"]["limit"]["minimum"],
                schema["properties"]["limit"]["maximum"],
            ) == (1, 20)

            by_name = {registered.name: registered for registered in tools}
            fetch = by_name["web_fetch"]
            assert (
                fetch.description is not None and "известных HTTP(S)-ресурсов" in fetch.description
            )
            assert fetch.annotations is not None
            assert (
                fetch.annotations.readOnlyHint,
                fetch.annotations.destructiveHint,
                fetch.annotations.idempotentHint,
                fetch.annotations.openWorldHint,
            ) == (False, False, False, True)
            assert set(fetch.inputSchema["properties"]) == {"urls"}
            fetch_urls = fetch.inputSchema["properties"]["urls"]
            assert (fetch_urls["minItems"], fetch_urls["maxItems"]) == (1, 8)
            assert (fetch_urls["items"]["minLength"], fetch_urls["items"]["maxLength"]) == (
                1,
                4096,
            )

            get = by_name["content_get"]
            assert get.description is not None and "без повторного HTTP-запроса" in get.description
            assert get.annotations is not None
            assert (
                get.annotations.readOnlyHint,
                get.annotations.destructiveHint,
                get.annotations.idempotentHint,
                get.annotations.openWorldHint,
            ) == (True, False, True, False)
            assert get.inputSchema["required"] == ["items"]
            assert set(get.inputSchema["properties"]) == {"items", "max_chars"}
            get_items = get.inputSchema["properties"]["items"]
            assert (get_items["minItems"], get_items["maxItems"]) == (1, 8)
            read_item = get_items["items"]
            assert read_item["required"] == ["content_id"]
            assert set(read_item["properties"]) == {"content_id", "cursor"}
            assert read_item["properties"]["cursor"]["type"] == "string"
            assert get.inputSchema["properties"]["max_chars"] == {
                "default": 12000,
                "description": ("Максимальное число Unicode-символов в каждом возвращаемом chunk."),
                "maximum": 30000,
                "minimum": 1,
                "type": "integer",
            }

            parse = by_name["content_parse"]
            assert (
                parse.description is not None and "canonical parser registry" in parse.description
            )
            assert parse.annotations is not None
            assert (
                parse.annotations.readOnlyHint,
                parse.annotations.destructiveHint,
                parse.annotations.idempotentHint,
                parse.annotations.openWorldHint,
            ) == (False, False, True, False)
            assert set(parse.inputSchema["properties"]) == {"content_ids"}
            parse_ids = parse.inputSchema["properties"]["content_ids"]
            assert (parse_ids["minItems"], parse_ids["maxItems"]) == (1, 8)
            assert parse_ids["uniqueItems"] is True
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as rest:
            assert (await rest.get("/health/live")).status_code == 200


def _http_errors(error: BaseException) -> list[httpx.HTTPStatusError]:
    if isinstance(error, httpx.HTTPStatusError):
        return [error]
    if isinstance(error, BaseExceptionGroup):
        return [nested for child in error.exceptions for nested in _http_errors(child)]
    return []


def _test_server(provider: StaticBearerAuthProvider) -> FastMCP:
    adapter = FastMcpAuthAdapter(provider)
    mcp = FastMCP(name="Web Access test", auth=adapter)

    @mcp.tool
    async def test_principal_context() -> dict[str, object]:
        """Test-only fixture; never registered by create_control_plane."""

        access_token = get_access_token()
        if access_token is None:
            raise RuntimeError("authenticated token context is missing")
        principal = adapter.principal_from_access_token(access_token)
        return {
            "principal_id": principal.principal_id,
            "principal_type": principal.principal_type.value,
            "scopes": sorted(principal.scopes),
        }

    return mcp


@pytest.mark.asyncio
async def test_principal_context_through_test_only_actual_tool(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = StaticBearerAuthProvider(settings.auth.principals)
    app = assemble_control_plane(settings, provider, _test_server(provider))
    async with app.router.lifespan_context(app):
        async with _client(app, TOKEN) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["test_principal_context"]
            assert tools[0].inputSchema.get("properties") == {}
            result = await client.call_tool("test_principal_context", {})
            assert result.data == {
                "principal_id": "mcp-agent",
                "principal_type": "service",
                "scopes": [
                    "admin:read",
                    "content:read",
                    "content:write",
                    "retrieval:read",
                    "search:read",
                ],
            }


def test_production_server_object_and_trusted_retry_descriptor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = StaticBearerAuthProvider(settings.auth.principals)
    mcp = create_mcp_server(provider)
    assert mcp.name == "Web Access"
    assert mcp.version == "0.3.0"
    descriptor = trusted_retry_descriptor("web_search")
    assert descriptor is not None
    assert descriptor.retry_class is RetryClass.PHASE_EVIDENCE_REQUIRED
    assert descriptor.effects.billable_cost_possible is True
    assert descriptor.blind_retry_after_possible_dispatch is False
    fetch = trusted_retry_descriptor("web_fetch")
    assert fetch is not None
    assert fetch.retry_class is RetryClass.PHASE_EVIDENCE_REQUIRED
    assert fetch.effects.resource_creation_possible is True
    assert fetch.blind_retry_after_possible_dispatch is False
    get = trusted_retry_descriptor("content_get")
    assert get is not None
    assert get.retry_class is RetryClass.SAFE_RETRY
    assert get.blind_retry_after_possible_dispatch is True
    parse = trusted_retry_descriptor("content_parse")
    assert parse is not None
    assert parse.retry_class is RetryClass.IDEMPOTENT_RETRY
    assert parse.effects.resource_creation_possible is True
    assert parse.idempotency_proven is True
    assert trusted_retry_descriptor("caller_supplied") is None


class _FakeSearch:
    def __init__(self) -> None:
        self.context: ExecutionContext | None = None
        self.request: SearchBatchRequest | None = None

    async def search(
        self, context: ExecutionContext, request: SearchBatchRequest
    ) -> OperationResult[SearchBatchResult]:
        self.context = context
        self.request = request
        now = datetime(2026, 8, 11, tzinfo=UTC)
        items = tuple(
            BatchItemResult[SearchQueryData](
                index=index,
                outcome=LeafOutcome.SUCCEEDED,
                data=SearchQueryData(
                    query=query.query,
                    provider_id=SearchProviderId.SEARXNG,
                    page=query.page,
                    requested_limit=query.limit,
                    results=(
                        SearchResultItem(
                            rank=1,
                            title=f"Result {index}",
                            url=f"https://example.test/{index}",
                        ),
                    ),
                    cache=CacheMetadata(cached=False, retrieved_at=now),
                    pagination=PaginationMetadata(page=query.page),
                ),
            )
            for index, query in enumerate(request.queries)
        )
        return OperationResult[SearchBatchResult](
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=SearchBatchResult(items=items),
        )


@pytest.mark.asyncio
async def test_actual_mcp_client_calls_shared_search_and_rejects_invalid_input(
    tmp_path: Path,
) -> None:
    fake_search = _FakeSearch()
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        app.state.mcp_runtime.bind(
            replace(
                app.state.container,
                search=cast(SearchApplicationService, fake_search),
            )
        )
        async with _client(app, TOKEN) as client:
            result = await client.call_tool(
                "web_search",
                {
                    "queries": ["  first  ", "second"],
                    "language": "EN-us",
                    "safe_search": "moderate",
                },
            )
            unknown = await client.call_tool(
                "web_search",
                {"queries": ["x"], "credential": "forbidden"},
                raise_on_error=False,
            )
            explicit_null = await client.call_tool(
                "web_search",
                {"queries": ["x"], "language": None},
                raise_on_error=False,
            )
        async with _client(app, NO_SCOPE_TOKEN) as client:
            denied = await client.call_tool("web_search", {"queries": ["x"]}, raise_on_error=False)

    assert result.structured_content is not None
    assert result.structured_content["outcome"] == "succeeded"
    assert [item["index"] for item in result.structured_content["data"]["items"]] == [0, 1]
    assert fake_search.context is not None
    assert fake_search.context.principal.principal_id == "mcp-agent"
    assert fake_search.request is not None
    assert fake_search.request.queries[0].query == "first"
    assert str(fake_search.request.queries[0].language) == "en-US"
    assert unknown.is_error is True
    assert explicit_null.is_error is True
    assert denied.is_error is False
    assert denied.structured_content is not None
    assert denied.structured_content["outcome"] == "rejected"
    assert denied.structured_content["error"]["category"] == "permission"
    assert denied.structured_content["error"]["code"] == "insufficient_scope"


CONTENT_ID = "cnt_" + "1" * 32


def _content_ref() -> ContentRef:
    return ContentRef(
        content_id=CONTENT_ID,
        media_type="text/plain",
        representation=ContentRepresentationKind.TEXT,
        size_bytes=3,
        sha256="a" * 64,
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def _content_inspection() -> ContentInspection:
    return ContentInspection(
        size_bytes=3,
        sha256="a" * 64,
        declared_media_type="text/plain",
        detected_media_type="text/plain",
        detected_format=ContentFormat.TEXT,
        encoding="utf-8",
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
        items = tuple(
            BatchItemResult(
                index=index,
                outcome=LeafOutcome.SUCCEEDED,
                data=RetrievalItemResult(
                    requested_url=item.url,
                    final_url=item.url,
                    http_status=200,
                    wire_bytes=3,
                    entity_bytes=3,
                    raw_content=_content_ref(),
                    inspection=_content_inspection(),
                    preview="abc",
                ),
            )
            for index, item in enumerate(request.items)
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=RetrievalBatchResult(items=items),
        )


class _FakeContent:
    def __init__(self) -> None:
        self.read_calls: list[tuple[str, int, str | None]] = []
        self.parse_context: ExecutionContext | None = None
        self.parse_ids: tuple[str, ...] | None = None

    async def read(
        self,
        context: ExecutionContext,
        content_id: str,
        *,
        max_chars: int = 12000,
        cursor: str | None = None,
    ) -> ContentReadResult:
        del context
        self.read_calls.append((content_id, max_chars, cursor))
        return ContentReadResult(
            content=_content_ref(),
            text="abc"[:max_chars],
            returned_chars=min(3, max_chars),
            inspection=_content_inspection(),
        )

    async def native_parse_many(
        self, context: ExecutionContext, content_ids: tuple[str, ...]
    ) -> OperationResult[ContentNativeParseBatchResult]:
        self.parse_context = context
        self.parse_ids = content_ids
        items = tuple(
            BatchItemResult(
                index=index,
                outcome=LeafOutcome.SUCCEEDED,
                data=NativeParseResult(
                    source=_content_ref(),
                    reused=True,
                    parser_capability="native.text",
                ),
            )
            for index, _content_id in enumerate(content_ids)
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=ContentNativeParseBatchResult(items=items),
        )


@pytest.mark.asyncio
async def test_actual_mcp_client_calls_shared_retrieval_and_content_services(
    tmp_path: Path,
) -> None:
    fake_retrieval = _FakeRetrieval()
    fake_content = _FakeContent()
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        app.state.mcp_runtime.bind(
            replace(
                app.state.container,
                retrieval=cast(RetrievalApplicationService, fake_retrieval),
                content=cast(ContentApplicationService, fake_content),
            )
        )
        async with _client(app, TOKEN) as client:
            fetched = await client.call_tool(
                "web_fetch",
                {"urls": ["https://example.test/a", "https://example.test/a"]},
            )
            read = await client.call_tool(
                "content_get",
                {"items": [{"content_id": CONTENT_ID}], "max_chars": 2},
            )
            parsed = await client.call_tool("content_parse", {"content_ids": [CONTENT_ID]})
            explicit_null = await client.call_tool(
                "content_get",
                {"items": [{"content_id": CONTENT_ID, "cursor": None}]},
                raise_on_error=False,
            )
            duplicate_parse = await client.call_tool(
                "content_parse",
                {"content_ids": [CONTENT_ID, CONTENT_ID]},
                raise_on_error=False,
            )
            parser_selector = await client.call_tool(
                "content_parse",
                {"content_ids": [CONTENT_ID], "parser": "pypdf"},
                raise_on_error=False,
            )
            processing_selector = await client.call_tool(
                "web_fetch",
                {
                    "urls": ["https://example.test/a"],
                    "processing_level": "store_only",
                },
                raise_on_error=False,
            )
            empty_fetch = await client.call_tool("web_fetch", {"urls": []}, raise_on_error=False)
            non_http_fetch = await client.call_tool(
                "web_fetch", {"urls": ["file:///etc/passwd"]}, raise_on_error=False
            )
            oversized_read = await client.call_tool(
                "content_get",
                {"items": [{"content_id": CONTENT_ID}], "max_chars": 30001},
                raise_on_error=False,
            )
        async with _client(app, NO_SCOPE_TOKEN) as client:
            parse_denied = await client.call_tool(
                "content_parse", {"content_ids": [CONTENT_ID]}, raise_on_error=False
            )

    assert fetched.structured_content is not None
    assert [item["index"] for item in fetched.structured_content["data"]["items"]] == [0, 1]
    assert fake_retrieval.context is not None
    assert fake_retrieval.context.principal.principal_id == "mcp-agent"
    assert fake_retrieval.request is not None
    assert fake_retrieval.request.processing_level is RetrievalProcessingLevel.NATIVE
    assert [item.url for item in fake_retrieval.request.items] == [
        "https://example.test/a",
        "https://example.test/a",
    ]
    assert read.structured_content is not None
    assert read.structured_content["data"]["items"][0]["data"]["text"] == "ab"
    assert fake_content.read_calls == [(CONTENT_ID, 2, None)]
    assert parsed.structured_content is not None
    assert parsed.structured_content["data"]["items"][0]["data"]["reused"] is True
    assert fake_content.parse_ids == (CONTENT_ID,)
    assert fake_content.parse_context is not None
    assert fake_content.parse_context.principal.principal_id == "mcp-agent"
    assert explicit_null.is_error is True
    assert duplicate_parse.is_error is True
    assert parser_selector.is_error is True
    assert processing_selector.is_error is True
    assert empty_fetch.is_error is True
    assert non_http_fetch.is_error is True
    assert oversized_read.is_error is True
    assert parse_denied.is_error is False
    assert parse_denied.structured_content is not None
    assert parse_denied.structured_content["outcome"] == "rejected"
    assert parse_denied.structured_content["error"]["code"] == "insufficient_scope"
