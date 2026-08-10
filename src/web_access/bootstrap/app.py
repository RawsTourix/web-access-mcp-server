"""Top-level FastAPI/FastMCP composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

from web_access.bootstrap.lifespan import runtime_lifespan
from web_access.core.config import Settings
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.infrastructure.observability.tracing import configure_tracing, instrument_fastapi
from web_access.transport.mcp.server import create_mcp_server
from web_access.transport.rest.app import create_rest_app


def assemble_control_plane(
    settings: Settings,
    auth_provider: StaticBearerAuthProvider,
    mcp: FastMCP,
) -> FastAPI:
    tracer_provider = configure_tracing(settings.observability, settings.app.service_name)

    @asynccontextmanager
    async def rest_lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_lifespan(
            settings, auth_provider, tracer_provider=tracer_provider
        ) as container:
            app.state.container = container
            yield

    app = create_rest_app(rest_lifespan)
    instrument_fastapi(app, tracer_provider)
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
    return assemble_control_plane(
        selected_settings,
        auth_provider,
        create_mcp_server(auth_provider),
    )
