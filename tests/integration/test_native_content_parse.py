from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.content.service import ContentApplicationService
from web_access.core.config import ContentStoreSettings, ParserSettings
from web_access.core.ids import DeterministicIdGenerator
from web_access.core.time import FakeClock
from web_access.domain.content import ContentId, ContentRepresentationKind
from web_access.infrastructure.content import FilesystemContentStore, RegistryContentIdentifier
from web_access.infrastructure.content.parsers import (
    ContentNativeParserRegistry,
    CsvNativeParser,
    InlineNativeParserExecutor,
    JsonNativeParser,
    TextNativeParser,
    XmlNativeParser,
)
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


def test_json_native_parse_publishes_derived_content_and_provenance(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for native Content parse tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(url)
        sessions = create_session_factory(engine)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(sessions)
        content_settings = ContentStoreSettings(root=tmp_path, chunk_size=4096)
        parser_settings = ParserSettings()
        store = FilesystemContentStore(content_settings)
        registry = ContentNativeParserRegistry(
            (
                TextNativeParser(parser_settings),
                JsonNativeParser(parser_settings),
                XmlNativeParser(parser_settings),
                CsvNativeParser(parser_settings),
            )
        )
        source_value = uuid4().hex
        derived_value = uuid4().hex
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter((source_value, derived_value))),
            uow_factory=uow_factory,
            store=store,
            identifier=RegistryContentIdentifier(available_formats=registry.available_formats),
            parser_registry=registry,
            parser_executor=InlineNativeParserExecutor(),
            inspection_sample_bytes=content_settings.inspection_sample_bytes,
            max_inspection_json_bytes=content_settings.max_inspection_json_bytes,
            parser_input_bytes=parser_settings.inline_max_input_bytes,
        )
        clock = FakeClock(datetime(2026, 8, 11, tzinfo=UTC))
        context = ExecutionContext(
            operation_id="op_native",
            principal=PrincipalContext("native-owner", frozenset({"content:read"})),
            clock=clock,
            cancellation=CancellationToken(),
        )
        raw_data = b'{"name":"Ada","roles":["engineer"]}'
        source = await service.ingest(
            context,
            _body(raw_data),
            representation_kind=ContentRepresentationKind.RAW,
            media_type="application/json",
            source_filename="profile.json",
        )
        parsed = await service.native_parse(context, source.content_id)

        assert parsed.parser_capability == "json"
        assert parsed.reused is False
        assert len(parsed.representations) == 1
        derived = parsed.representations[0]
        assert derived.representation is ContentRepresentationKind.STRUCTURED

        async with uow_factory() as uow:
            source_record = await uow.contents.get(ContentId(source.content_id))
            derived_record = await uow.contents.get(ContentId(derived.content_id))
            relations = await uow.relations.for_source(ContentId(source.content_id))
        assert source_record is not None
        assert derived_record is not None
        assert source_record.content.representation_kind is ContentRepresentationKind.RAW
        assert derived_record.content.source_content_id == ContentId(source.content_id)
        assert derived_record.content.producer_capability == "json"
        assert derived_record.content.producer_revision == "json-stdlib-v1"
        assert derived_record.content.representation_schema_revision == "content-json-v1"
        assert len(relations) == 1
        assert relations[0].target_content_id == ContentId(derived.content_id)
        assert derived_record.storage_key is not None
        stored = b"".join([chunk async for chunk in store.open_stream(derived_record.storage_key)])
        assert json.loads(stored)["value"] == {"name": "Ada", "roles": ["engineer"]}
        assert (
            b"".join([chunk async for chunk in store.open_stream(source_record.storage_key or "")])
            == raw_data
        )
        await engine.dispose()

    asyncio.run(run())
