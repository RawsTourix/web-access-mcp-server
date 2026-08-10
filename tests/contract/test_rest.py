from __future__ import annotations

from pathlib import Path
from typing import Literal

import httpx
import pytest
from pydantic import SecretStr

from web_access.bootstrap.app import create_control_plane
from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    Environment,
    PrincipalSettings,
    Settings,
)

TOKEN = "a" * 32
NO_SCOPE_TOKEN = "b" * 32


DependencyName = Literal["postgres", "redis", "content_store"]


def _settings(tmp_path: Path, mandatory: frozenset[DependencyName] = frozenset()) -> Settings:
    return Settings(
        app=AppSettings(
            environment=Environment.TEST,
            mandatory_dependencies=mandatory,
        ),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="diagnostic-agent",
                    tokens=(SecretStr(TOKEN),),
                    scopes=frozenset({"admin:read"}),
                ),
                PrincipalSettings(
                    principal_id="limited-agent",
                    tokens=(SecretStr(NO_SCOPE_TOKEN),),
                    scopes=frozenset({"content:read"}),
                ),
            )
        ),
        content_store=ContentStoreSettings(root=tmp_path),
    )


@pytest.mark.asyncio
async def test_operational_routes_auth_and_safe_status(tmp_path: Path) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            live = await client.get("/health/live")
            assert live.status_code == 200
            assert live.json() == {"status": "alive"}
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready"}

            missing = await client.get("/health/status")
            invalid = await client.get(
                "/health/status", headers={"Authorization": "Bearer invalid-credential"}
            )
            denied = await client.get(
                "/health/status", headers={"Authorization": f"Bearer {NO_SCOPE_TOKEN}"}
            )
            assert missing.status_code == 401
            assert missing.json()["error"]["code"] == "missing_credentials"
            assert invalid.status_code == 401
            assert invalid.json()["error"]["code"] == "invalid_credentials"
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "insufficient_scope"

            status = await client.get(
                "/health/status", headers={"Authorization": f"Bearer {TOKEN}"}
            )
            assert status.status_code == 200
            rendered = status.text
            assert TOKEN not in rendered
            assert "postgresql+asyncpg" not in rendered
            assert str(tmp_path) not in rendered
            metrics = await client.get("/metrics")
            assert metrics.status_code == 200
            assert "web_access_http_requests_total" in metrics.text


@pytest.mark.asyncio
async def test_liveness_survives_mandatory_dependency_outage(tmp_path: Path) -> None:
    app = create_control_plane(
        _settings(tmp_path, frozenset({"postgres", "redis", "content_store"}))
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            ready = await client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_correlation_headers_are_bounded_and_server_owned(tmp_path: Path) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            accepted = await client.get("/health/live", headers={"X-Request-ID": "caller-123"})
            assert accepted.headers["X-Request-ID"] == "caller-123"
            assert accepted.headers["X-Operation-ID"].startswith("op_")
            rejected = await client.get("/health/live", headers={"X-Request-ID": "bad value"})
            assert rejected.headers["X-Request-ID"].startswith("req_")


def test_openapi_has_only_foundation_routes_and_bearer_security(tmp_path: Path) -> None:
    schema = create_control_plane(_settings(tmp_path)).openapi()
    assert set(schema["paths"]) == {
        "/health/live",
        "/health/ready",
        "/health/status",
        "/metrics",
    }
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    status_operation = schema["paths"]["/health/status"]["get"]
    assert status_operation["security"] == [{"BearerAuth": []}]
    rendered = str(schema).lower()
    for forbidden in ("search", "retrieval", "browser", "jobs", "sqlalchemy", "redis_url"):
        assert f'"/{forbidden}' not in rendered
