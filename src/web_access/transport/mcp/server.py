"""FastMCP Streamable HTTP server and shared Control Plane assembly."""

from __future__ import annotations

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

from web_access.core.config import Settings
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.rest.app import create_rest_app


def create_mcp_server(auth_provider: StaticBearerAuthProvider) -> FastMCP:
    """Create the intentionally empty v0.1 production catalog."""

    return FastMCP(
        name="Web Access",
        version="0.1.0",
        instructions="Service Foundation: production business tools are not registered yet.",
        auth=FastMcpAuthAdapter(auth_provider),
        mask_error_details=True,
        strict_input_validation=True,
    )


def assemble_control_plane(
    settings: Settings,
    auth_provider: StaticBearerAuthProvider,
    mcp: FastMCP,
) -> FastAPI:
    """Mount MCP beside REST while preserving both lifespans and one backend."""

    app = create_rest_app(settings, auth_provider)
    mcp_app = mcp.http_app(path="/", transport="streamable-http")
    app.router.lifespan_context = combine_lifespans(
        app.router.lifespan_context,
        mcp_app.lifespan,
    )
    app.mount("/mcp", mcp_app, name="mcp")
    app.state.mcp_server = mcp
    return app


def create_control_plane(settings: Settings | None = None) -> FastAPI:
    selected_settings = settings or Settings()
    auth_provider = StaticBearerAuthProvider(selected_settings.auth.principals)
    mcp = create_mcp_server(auth_provider)
    return assemble_control_plane(selected_settings, auth_provider, mcp)
