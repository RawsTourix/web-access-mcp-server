from __future__ import annotations

import asyncio
import io
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pypdf import PdfWriter
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
from web_access.domain.content import ContentId, ContentRepresentationKind, ContentState
from web_access.infrastructure.content import FilesystemContentStore, RegistryContentIdentifier
from web_access.infrastructure.content.parser_isolation import (
    IsolatedParserFailure,
    SubprocessParserExecutor,
)
from web_access.infrastructure.content.parsers import (
    ContentNativeParserRegistry,
    PdfNativeParser,
    RoutingNativeParserExecutor,
)
from web_access.infrastructure.database.content import SqlAlchemyContentUnitOfWorkFactory
from web_access.infrastructure.database.engine import create_session_factory

pytestmark = pytest.mark.integration


class ReducedDevelopmentExecutor(SubprocessParserExecutor):
    @property
    def hard_network_isolation(self) -> bool:
        return False


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _blank_pdf(*, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("not-accepted-by-api")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_parse_persists_diagnostics_and_encrypted_failure_keeps_raw(tmp_path) -> None:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if url is None:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for PDF Content parse tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(url)
        sessions = create_session_factory(engine)
        uow_factory = SqlAlchemyContentUnitOfWorkFactory(sessions)
        content_settings = ContentStoreSettings(root=tmp_path / "content")
        parser_settings = ParserSettings(child_temp_root=tmp_path / "parser")
        store = FilesystemContentStore(content_settings)
        parser = PdfNativeParser()
        registry = ContentNativeParserRegistry((parser,))
        isolated = ReducedDevelopmentExecutor(
            parser_settings,
            allowed_parser_ids=frozenset({"pdf"}),
            allow_reduced_isolation=True,
        )
        service = ContentApplicationService(
            ids=DeterministicIdGenerator(iter(uuid4().hex for _ in range(3))),
            uow_factory=uow_factory,
            store=store,
            identifier=RegistryContentIdentifier(available_formats=registry.available_formats),
            parser_registry=registry,
            parser_executor=RoutingNativeParserExecutor(
                settings=parser_settings, isolated=isolated
            ),
            parser_input_bytes=max(
                parser_settings.inline_max_input_bytes, parser_settings.pdf_max_bytes
            ),
        )
        clock = FakeClock(datetime(2026, 8, 11, tzinfo=UTC))
        context = ExecutionContext(
            operation_id="op_pdf",
            principal=PrincipalContext("pdf-owner", frozenset({"content:read"})),
            clock=clock,
            cancellation=CancellationToken(),
        )
        blank = await service.ingest(
            context,
            _body(_blank_pdf()),
            representation_kind=ContentRepresentationKind.RAW,
            media_type="application/pdf",
            source_filename="scan.pdf",
        )
        parsed = await service.native_parse(context, blank.content_id)
        assert [item.representation for item in parsed.representations] == [
            ContentRepresentationKind.STRUCTURED
        ]
        assert parsed.warnings[0].code == "pdf_native_text_unavailable"
        assert parsed.hints[0].code == "advanced_processing_may_be_required"

        async with uow_factory() as uow:
            derived = await uow.contents.get(ContentId(parsed.representations[0].content_id))
        assert derived is not None
        assert derived.content.producer_capability == "pdf"

        encrypted = await service.ingest(
            context,
            _body(_blank_pdf(encrypted=True)),
            representation_kind=ContentRepresentationKind.RAW,
            media_type="application/pdf",
            source_filename="encrypted.pdf",
        )
        with pytest.raises(IsolatedParserFailure) as failure:
            await service.native_parse(context, encrypted.content_id)
        assert failure.value.code == "encrypted_content"
        async with uow_factory() as uow:
            encrypted_record = await uow.contents.get(ContentId(encrypted.content_id))
        assert encrypted_record is not None
        assert encrypted_record.content.state is ContentState.AVAILABLE
        assert encrypted_record.content.representation_kind is ContentRepresentationKind.RAW
        await engine.dispose()

    asyncio.run(run())
