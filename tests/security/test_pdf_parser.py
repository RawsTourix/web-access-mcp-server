from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from web_access.application.content.models import ContentInspection
from web_access.core.config import ParserSettings
from web_access.domain.content import (
    ContentFormat,
    ContentId,
    ContentObject,
    ContentRepresentationKind,
    ContentState,
    ParserAvailability,
)
from web_access.infrastructure.content.parser_isolation import (
    IsolatedParserFailure,
    SubprocessParserExecutor,
)
from web_access.infrastructure.content.parsers import (
    PdfNativeParser,
    RoutingNativeParserExecutor,
)


class ReducedDevelopmentExecutor(SubprocessParserExecutor):
    @property
    def hard_network_isolation(self) -> bool:
        return False


def _source(data: bytes) -> ContentObject:
    return ContentObject(
        content_id=ContentId("cnt_" + "3" * 32),
        owner_principal_id="owner",
        state=ContentState.AVAILABLE,
        revision=4,
        representation_kind=ContentRepresentationKind.RAW,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="application/pdf",
        size_bytes=len(data),
        sha256="c" * 64,
    )


def _inspection(data: bytes) -> ContentInspection:
    return ContentInspection(
        size_bytes=len(data),
        sha256="c" * 64,
        declared_media_type="application/pdf",
        detected_media_type="application/pdf",
        detected_format=ContentFormat.PDF,
        parser_availability=ParserAvailability.AVAILABLE,
    )


def _routing(
    tmp_path,
    *,
    pdf_max_pages: int = 200,
    pdf_max_content_stream_bytes: int = 8 * 1024 * 1024,
    pdf_max_page_chars: int = 200_000,
    pdf_max_output_chars: int = 2_000_000,
) -> RoutingNativeParserExecutor:
    settings = ParserSettings(
        child_temp_root=tmp_path / "parser-root",
        pdf_max_pages=pdf_max_pages,
        pdf_max_content_stream_bytes=pdf_max_content_stream_bytes,
        pdf_max_page_chars=pdf_max_page_chars,
        pdf_max_output_chars=pdf_max_output_chars,
    )
    isolated = ReducedDevelopmentExecutor(
        settings,
        allowed_parser_ids=frozenset({"pdf"}),
        allow_reduced_isolation=True,
    )
    return RoutingNativeParserExecutor(settings=settings, isolated=isolated)


async def _parse(
    tmp_path,
    data: bytes,
    *,
    pdf_max_pages: int = 200,
    pdf_max_content_stream_bytes: int = 8 * 1024 * 1024,
    pdf_max_page_chars: int = 200_000,
    pdf_max_output_chars: int = 2_000_000,
):
    return await _routing(
        tmp_path,
        pdf_max_pages=pdf_max_pages,
        pdf_max_content_stream_bytes=pdf_max_content_stream_bytes,
        pdf_max_page_chars=pdf_max_page_chars,
        pdf_max_output_chars=pdf_max_output_chars,
    ).execute(PdfNativeParser(), _source(data), _inspection(data), data)


def _pdf(*page_texts: str | None, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for page_text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        if page_text is not None:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            resources = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    )
                }
            )
            stream = DecodedStreamObject()
            safe_text = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode())
            page[NameObject("/Resources")] = resources
            page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Bounded PDF fixture"})
    if encrypted:
        writer.encrypt("fixture-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_text_pdf_returns_native_text_and_bounded_structure(tmp_path) -> None:
    data = _pdf("First page text", "Second page text")
    result = await _parse(tmp_path, data)

    text = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.TEXT
    )
    structure_item = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.STRUCTURED
    )
    assert "First page text" in text.data.decode()
    assert "Second page text" in text.data.decode()
    structure = json.loads(structure_item.data)
    assert structure["schema_revision"] == "content-pdf-structure-v1"
    assert structure["page_count"] == 2
    assert structure["metadata"]["/Title"] == "Bounded PDF fixture"
    assert result.hints == ()


@pytest.mark.asyncio
async def test_image_only_pdf_returns_diagnostic_and_no_text_representation(tmp_path) -> None:
    result = await _parse(tmp_path, _pdf(None))

    assert [item.representation for item in result.representations] == [
        ContentRepresentationKind.STRUCTURED
    ]
    assert [warning.code for warning in result.warnings] == ["pdf_native_text_unavailable"]
    assert [hint.code for hint in result.hints] == ["advanced_processing_may_be_required"]


@pytest.mark.asyncio
async def test_encrypted_and_malformed_pdf_are_normalized_without_password_or_ocr(tmp_path) -> None:
    with pytest.raises(IsolatedParserFailure) as encrypted:
        await _parse(tmp_path, _pdf("secret", encrypted=True))
    assert encrypted.value.code == "encrypted_content"

    with pytest.raises(IsolatedParserFailure) as malformed:
        await _parse(tmp_path, b"%PDF-1.7\nmalformed and truncated")
    assert malformed.value.code == "malformed_pdf"


@pytest.mark.asyncio
async def test_pdf_page_and_content_stream_limits_fail_before_unbounded_output(tmp_path) -> None:
    with pytest.raises(IsolatedParserFailure) as pages:
        await _parse(tmp_path, _pdf("one", "two"), pdf_max_pages=1)
    assert pages.value.code == "pdf_page_limit"

    with pytest.raises(IsolatedParserFailure) as stream:
        await _parse(
            tmp_path,
            _pdf("x" * 2000),
            pdf_max_content_stream_bytes=1024,
        )
    assert stream.value.code == "pdf_content_stream_limit"


@pytest.mark.asyncio
async def test_pdf_text_output_is_truncated_by_page_and_total_character_limits(tmp_path) -> None:
    result = await _parse(
        tmp_path,
        _pdf("a" * 500, "b" * 500),
        pdf_max_page_chars=200,
        pdf_max_output_chars=250,
    )
    text = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.TEXT
    )
    assert len(text.data.decode()) <= 260
    assert {warning.code for warning in result.warnings} == {
        "pdf_page_text_truncated",
        "pdf_text_truncated",
    }
