from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.bootstrap.app import create_control_plane
from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    DatabaseSettings,
    Environment,
    PrincipalSettings,
    Settings,
)
from web_access.core.ids import IdPrefix
from web_access.domain.content import ContentRepresentationKind

pytestmark = pytest.mark.integration

TOKEN = "rest-content-owner-token-value-32"
OTHER_TOKEN = "rest-content-other-token-value-32"


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


def test_real_rest_content_backend_metadata_stream_inspect_and_parse(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for REST Content tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    settings = Settings(
        app=AppSettings(environment=Environment.TEST, mandatory_dependencies=frozenset()),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="rest-content-owner",
                    tokens=(SecretStr(TOKEN),),
                    scopes=frozenset({"content:read", "content:write"}),
                ),
                PrincipalSettings(
                    principal_id="other-owner",
                    tokens=(SecretStr(OTHER_TOKEN),),
                    scopes=frozenset({"content:read", "content:write"}),
                ),
            )
        ),
        database=DatabaseSettings.model_validate({"url": url}),
        content_store=ContentStoreSettings(root=tmp_path, chunk_size=4096),
    )

    async def run() -> None:
        app = create_control_plane(settings)
        async with app.router.lifespan_context(app):
            container = app.state.container
            context = ExecutionContext(
                operation_id=container.ids.new(IdPrefix.OPERATION),
                principal=PrincipalContext(
                    "rest-content-owner", frozenset({"content:read", "content:write"})
                ),
                clock=container.clock,
                cancellation=CancellationToken(),
            )
            raw = b'{"name":"Ada","language":"Python"}'
            source = await container.content.ingest(
                context,
                _body(raw),
                representation_kind=ContentRepresentationKind.RAW,
                media_type="application/json",
                source_filename="profile.json",
            )
            owner = {"Authorization": f"Bearer {TOKEN}"}
            other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                metadata = await client.get(f"/api/v1/content/{source.content_id}", headers=owner)
                denied = await client.get(f"/api/v1/content/{source.content_id}", headers=other)
                data = await client.get(f"/api/v1/content/{source.content_id}/data", headers=owner)
                inspected = await client.post(
                    "/api/v1/content/inspect",
                    headers=owner,
                    json={"content_ids": [source.content_id]},
                )
                parsed = await client.post(
                    "/api/v1/content/native-parse",
                    headers=owner,
                    json={"content_ids": [source.content_id]},
                )
                representations = await client.get(
                    f"/api/v1/content/{source.content_id}/representations", headers=owner
                )

            assert metadata.status_code == 200
            assert metadata.json()["data"]["content"] == source.model_dump(mode="json")
            assert denied.status_code == 403
            assert data.status_code == 200 and data.content == raw
            assert data.headers["content-type"] == "application/json"
            assert inspected.status_code == 200
            assert (
                inspected.json()["data"]["items"][0]["data"]["inspection"]["detected_format"]
                == "json"
            )
            assert parsed.status_code == 200
            parsed_item = parsed.json()["data"]["items"][0]["data"]
            assert parsed_item["parser_capability"] == "json"
            assert parsed_item["reused"] is False
            assert representations.status_code == 200
            summaries = representations.json()["data"]["representations"]
            assert len(summaries) == 1
            assert summaries[0]["provenance"]["source_content_id"] == source.content_id

    asyncio.run(run())
