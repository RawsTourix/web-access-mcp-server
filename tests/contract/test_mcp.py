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
                    scopes=frozenset({"admin:read", "search:read"}),
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
            assert [tool.name for tool in tools] == ["web_search"]
            tool = tools[0]
            assert tool.description is not None
            assert "Не читает содержимое" in tool.description  # noqa: RUF001
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
                "scopes": ["admin:read", "search:read"],
            }


def test_production_server_object_and_trusted_retry_descriptor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = StaticBearerAuthProvider(settings.auth.principals)
    mcp = create_mcp_server(provider)
    assert mcp.name == "Web Access"
    descriptor = trusted_retry_descriptor("web_search")
    assert descriptor is not None
    assert descriptor.retry_class is RetryClass.PHASE_EVIDENCE_REQUIRED
    assert descriptor.effects.billable_cost_possible is True
    assert descriptor.blind_retry_after_possible_dispatch is False
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
    assert denied.is_error is True
