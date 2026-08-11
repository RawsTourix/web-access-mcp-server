from __future__ import annotations

import pytest

from web_access.domain.content import ContentFormat, ParserAvailability
from web_access.infrastructure.content.identifier import RegistryContentIdentifier


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "filename", "declared", "expected"),
    [
        (b"<!doctype html><html><body>x</body></html>", "page.bin", None, ContentFormat.HTML),
        (b'{"key": [1, 2]}', "payload.bin", None, ContentFormat.JSON),
        (b"<?xml version='1.0'?><root/>", "payload.bin", None, ContentFormat.XML),
        (b"name,age\nAda,36\nGrace,40\n", "payload.bin", None, ContentFormat.CSV),
        (b"ordinary readable text\n", "payload.bin", None, ContentFormat.TEXT),
        (b"\x00\x01\x02\xff", "payload.txt", "text/plain", ContentFormat.UNKNOWN),
    ],
)
async def test_registry_uses_bounded_content_evidence_not_mime_or_suffix_alone(
    data: bytes,
    filename: str,
    declared: str | None,
    expected: ContentFormat,
) -> None:
    result = await RegistryContentIdentifier().inspect(
        data,
        size_bytes=len(data),
        sha256="a" * 64,
        declared_media_type=declared,
        source_filename=filename,
    )
    assert result.detected_format is expected


@pytest.mark.asyncio
async def test_pdf_magic_overrides_conflicting_mime_and_filename_with_warning() -> None:
    data = b"%PDF-1.7\n% bounded evidence"
    result = await RegistryContentIdentifier(
        available_formats=frozenset({ContentFormat.PDF})
    ).inspect(
        data,
        size_bytes=12345,
        sha256="b" * 64,
        declared_media_type="text/plain; charset=utf-8",
        source_filename="notes.txt",
    )

    assert result.size_bytes == 12345
    assert result.detected_format is ContentFormat.PDF
    assert result.detected_media_type == "application/pdf"
    assert result.declared_media_type == "text/plain"
    assert result.parser_availability is ParserAvailability.AVAILABLE
    assert [warning.code for warning in result.warnings] == ["declared_content_type_mismatch"]


@pytest.mark.asyncio
async def test_inspection_sanitizes_filename_and_reports_observed_utf8() -> None:
    data = "Привет, Content".encode()
    result = await RegistryContentIdentifier().inspect(
        data,
        size_bytes=len(data),
        sha256="c" * 64,
        declared_media_type="text/plain",
        source_filename="../unsafe\\name.txt",
    )

    assert result.source_filename == "_unsafe_name.txt"
    assert result.encoding == "utf-8"
    assert result.parser_availability is ParserAvailability.UNSUPPORTED


@pytest.mark.asyncio
async def test_declared_valid_charset_is_preserved_as_decoding_evidence() -> None:
    data = "Привет".encode("windows-1251")
    result = await RegistryContentIdentifier().inspect(
        data,
        size_bytes=len(data),
        sha256="d" * 64,
        declared_media_type="text/plain; charset=windows-1251",
        source_filename="message.txt",
    )
    assert result.detected_format is ContentFormat.TEXT
    assert result.encoding == "windows-1251"
