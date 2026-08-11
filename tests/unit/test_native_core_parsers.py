from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

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
from web_access.infrastructure.content.parsers import (
    ContentNativeParserRegistry,
    CsvNativeParser,
    HtmlNativeParser,
    JsonNativeParser,
    PdfNativeParser,
    TextNativeParser,
    XmlNativeParser,
)
from web_access.infrastructure.content.parsers.common import (
    NativeParserError,
    ParserDepthLimitExceeded,
    ParserOutputLimitExceeded,
)


def _source() -> ContentObject:
    return ContentObject(
        content_id=ContentId("cnt_" + "1" * 32),
        owner_principal_id="owner",
        state=ContentState.AVAILABLE,
        revision=4,
        representation_kind=ContentRepresentationKind.RAW,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="application/octet-stream",
        size_bytes=4,
        sha256="a" * 64,
    )


def _inspection(
    content_format: ContentFormat, *, encoding: str | None = "utf-8"
) -> ContentInspection:
    return ContentInspection(
        size_bytes=4,
        sha256="a" * 64,
        detected_media_type="application/octet-stream",
        detected_format=content_format,
        encoding=encoding,
        parser_availability=ParserAvailability.AVAILABLE,
    )


@pytest.mark.asyncio
async def test_text_parser_honors_observed_encoding_and_normalizes_utf8() -> None:
    parser = TextNativeParser(ParserSettings())
    value = "Привет, мир"
    result = await parser.parse(
        _source(),
        _inspection(ContentFormat.TEXT, encoding="windows-1251"),
        value.encode("windows-1251"),
    )
    representation = result.representations[0]
    assert representation.representation is ContentRepresentationKind.TEXT
    assert representation.data.decode() == value
    assert representation.media_type == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_json_parser_emits_versioned_schema_and_enforces_depth_and_output() -> None:
    parser = JsonNativeParser(ParserSettings(structured_max_depth=3))
    result = await parser.parse(_source(), _inspection(ContentFormat.JSON), b'{"safe":[1,2]}')
    value = json.loads(result.representations[0].data)
    assert value == {"schema_revision": "content-json-v1", "value": {"safe": [1, 2]}}

    with pytest.raises(ParserDepthLimitExceeded):
        await parser.parse(_source(), _inspection(ContentFormat.JSON), b'{"a":{"b":{"c":1}}}')

    small_output = JsonNativeParser(ParserSettings(inline_max_output_bytes=1024))
    with pytest.raises(ParserOutputLimitExceeded):
        await small_output.parse(
            _source(),
            _inspection(ContentFormat.JSON),
            json.dumps({"value": "x" * 2000}).encode(),
        )


@pytest.mark.asyncio
async def test_xml_parser_rejects_entities_and_bounds_depth() -> None:
    parser = XmlNativeParser(ParserSettings(structured_max_depth=3))
    result = await parser.parse(
        _source(),
        _inspection(ContentFormat.XML),
        b"<root><item id='1'>safe</item></root>",
    )
    value = json.loads(result.representations[0].data)
    assert value["schema_revision"] == "content-xml-v1"
    assert value["root"]["children"][0]["tag"] == "item"

    entity = b'<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>'
    with pytest.raises(NativeParserError):
        await parser.parse(_source(), _inspection(ContentFormat.XML), entity)

    with pytest.raises(ParserDepthLimitExceeded):
        await parser.parse(_source(), _inspection(ContentFormat.XML), b"<a><b><c><d/></c></b></a>")


@pytest.mark.asyncio
async def test_csv_parser_bounds_rows_columns_cells_and_owns_schema() -> None:
    parser = CsvNativeParser(ParserSettings(csv_max_rows=2, csv_max_columns=3))
    result = await parser.parse(
        _source(),
        _inspection(ContentFormat.CSV),
        b"name,age\nAda,36\nGrace,40\n",
    )
    value = json.loads(result.representations[0].data)
    assert value["schema_revision"] == "content-csv-v1"
    assert value["rows"] == [["name", "age"], ["Ada", "36"]]
    assert value["truncated"] is True

    with pytest.raises(NativeParserError):
        await parser.parse(_source(), _inspection(ContentFormat.CSV), b"a,b,c,d\n1,2,3,4\n")


def test_registry_rejects_ambiguous_format_ownership() -> None:
    settings = ParserSettings()
    registry = ContentNativeParserRegistry(
        (
            TextNativeParser(settings),
            JsonNativeParser(settings),
            XmlNativeParser(settings),
            CsvNativeParser(settings),
            HtmlNativeParser(settings),
            PdfNativeParser(),
        )
    )
    assert registry.available_formats == frozenset(
        {
            ContentFormat.TEXT,
            ContentFormat.JSON,
            ContentFormat.XML,
            ContentFormat.CSV,
            ContentFormat.HTML,
            ContentFormat.PDF,
        }
    )
    selected = registry.select(_inspection(ContentFormat.JSON))
    assert selected is not None
    assert selected.descriptor.capability == "json"
    with pytest.raises(ValueError, match="duplicate native parser"):
        ContentNativeParserRegistry((TextNativeParser(settings), TextNativeParser(settings)))
