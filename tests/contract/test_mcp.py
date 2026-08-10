from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_access_token
from pydantic import SecretStr

from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    Environment,
    PrincipalSettings,
    Settings,
)
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.mcp.server import (
    assemble_control_plane,
    create_control_plane,
    create_mcp_server,
)

TOKEN = "m" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app=AppSettings(environment=Environment.TEST, mandatory_dependencies=frozenset()),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="mcp-agent",
                    tokens=(SecretStr(TOKEN),),
                    scopes=frozenset({"admin:read"}),
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
async def test_actual_mcp_client_auth_and_empty_production_catalog(tmp_path: Path) -> None:
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
            assert await client.list_tools() == []
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
    mcp = create_mcp_server(provider)
    adapter = FastMcpAuthAdapter(provider)

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
                "scopes": ["admin:read"],
            }


def test_production_server_object_has_no_tools(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = StaticBearerAuthProvider(settings.auth.principals)
    mcp = create_mcp_server(provider)
    assert mcp.name == "Web Access"
