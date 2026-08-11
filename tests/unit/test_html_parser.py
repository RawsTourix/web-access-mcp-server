from __future__ import annotations

import json
import socket
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
from web_access.infrastructure.content.parsers import HtmlNativeParser


def _source() -> ContentObject:
    return ContentObject(
        content_id=ContentId("cnt_" + "2" * 32),
        owner_principal_id="owner",
        state=ContentState.AVAILABLE,
        revision=4,
        representation_kind=ContentRepresentationKind.RAW,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="text/html",
        size_bytes=4,
        sha256="b" * 64,
    )


def _inspection() -> ContentInspection:
    return ContentInspection(
        size_bytes=4,
        sha256="b" * 64,
        declared_media_type="text/html",
        detected_media_type="text/html",
        detected_format=ContentFormat.HTML,
        encoding="utf-8",
        parser_availability=ParserAvailability.AVAILABLE,
    )


@pytest.mark.asyncio
async def test_html_separates_main_content_from_bounded_structure_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("HTML parsing attempted network access")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    paragraph = "Readable reporting content with enough detail for extraction. " * 25
    document = f"""
    <!doctype html><html><head>
      <title>Example report</title>
      <meta name="description" content="Bounded description">
      <meta property="og:title" content="OpenGraph report">
      <link rel="canonical" href="https://example.com/canonical">
      <script type="application/ld+json">
        {{"@type":"Article","payload":"__import__('os').system('bad')"}}
      </script>
    </head><body><article><h1>Report heading</h1><p>{paragraph}</p>
      <a href="https://unreachable.invalid/one">First link</a>
      <a href="https://unreachable.invalid/two">Second link</a>
      <img src="https://unreachable.invalid/image.png">
    </article></body></html>
    """.encode()
    parser = HtmlNativeParser(ParserSettings(html_max_links=1, html_max_headings=1))

    result = await parser.parse(_source(), _inspection(), document)

    markdown = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.MARKDOWN
    )
    structure_representation = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.STRUCTURED
    )
    assert "Readable reporting content" in markdown.data.decode()
    structure = json.loads(structure_representation.data)
    assert structure["schema_revision"] == "content-html-structure-v1"
    assert structure["title"] == "Example report"
    assert structure["canonical_url"] == "https://example.com/canonical"
    assert structure["description"] == "Bounded description"
    assert structure["headings"] == [{"level": 1, "text": "Report heading"}]
    assert structure["links"] == [{"href": "https://unreachable.invalid/one", "text": "First link"}]
    assert structure["open_graph"] == {"og:title": "OpenGraph report"}
    assert structure["json_ld"][0]["payload"] == "__import__('os').system('bad')"
    assert result.hints == ()


@pytest.mark.asyncio
async def test_script_shell_returns_structural_partial_and_trusted_hint_only() -> None:
    document = b"""
    <html><head><title>Application</title></head><body>
      <div id="root"></div><script type="module" src="/assets/app.js"></script>
    </body></html>
    """
    result = await HtmlNativeParser(ParserSettings()).parse(_source(), _inspection(), document)

    assert [item.representation for item in result.representations] == [
        ContentRepresentationKind.STRUCTURED
    ]
    assert [warning.code for warning in result.warnings] == ["html_main_content_unavailable"]
    assert [hint.code for hint in result.hints] == ["browser_may_be_required"]
    assert result.hints[0].related_capability == "browser"


@pytest.mark.asyncio
async def test_html_metadata_and_main_output_are_hard_bounded() -> None:
    document = (
        "<html><head><script type='application/ld+json'>"
        + "x" * 1000
        + "</script></head><body><article><p>"
        + ("bounded text " * 1000)
        + "</p></article></body></html>"
    ).encode()
    settings = ParserSettings(
        html_max_text_chars=1024,
        html_max_metadata_chars=128,
        inline_max_output_bytes=2048,
    )
    result = await HtmlNativeParser(settings).parse(_source(), _inspection(), document)

    markdown = next(
        item
        for item in result.representations
        if item.representation is ContentRepresentationKind.MARKDOWN
    )
    assert len(markdown.data) <= settings.inline_max_output_bytes
    assert "html_main_content_truncated" in {warning.code for warning in result.warnings}
    assert "html_jsonld_oversized" in {warning.code for warning in result.warnings}
