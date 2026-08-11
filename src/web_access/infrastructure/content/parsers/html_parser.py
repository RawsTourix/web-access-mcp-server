"""No-network HTML main-content and structural extraction."""

from __future__ import annotations

import json
import re

import trafilatura
from lxml import html
from lxml.etree import ParserError

from web_access.application.common.hints import (
    StructuredHint,
    Warning,
    browser_may_be_required,
)
from web_access.application.content.models import (
    ContentInspection,
    NativeParserOutput,
    ParsedRepresentation,
    ParserDescriptor,
)
from web_access.core.config import ParserSettings
from web_access.domain.content import (
    ContentFormat,
    ContentObject,
    ContentRepresentationKind,
)
from web_access.infrastructure.content.parsers.common import (
    NativeParserError,
    bounded_json_bytes,
    json_depth,
    require_input_bound,
)

_SPACE = re.compile(r"\s+")
_OG_KEYS = frozenset(
    {"og:title", "og:description", "og:image", "og:url", "og:type", "og:site_name"}
)
_SHELL_IDS = frozenset({"app", "root", "__next", "___gatsby"})


class HtmlNativeParser:
    def __init__(self, settings: ParserSettings) -> None:
        self._settings = settings

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="html",
            revision="html-trafilatura-lxml-v1",
            profile_revision="html-default-v1",
            supported_formats=(ContentFormat.HTML,),
            primary_representation=ContentRepresentationKind.MARKDOWN,
            representation_schema_revision="content-html-main-v1",
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source
        require_input_bound(data, self._settings.inline_max_input_bytes)
        try:
            document = data.decode(inspection.encoding or "utf-8", errors="replace")
            root = html.fromstring(
                data,
                parser=html.HTMLParser(
                    encoding=inspection.encoding or "utf-8",
                    recover=True,
                    no_network=True,
                    remove_comments=True,
                ),
            )
        except (LookupError, ParserError, ValueError) as error:
            raise NativeParserError("invalid HTML Content") from error

        representations: list[ParsedRepresentation] = []
        warnings: list[Warning] = []
        hints: list[StructuredHint] = []
        script_shell = _is_script_shell(root)
        main = trafilatura.extract(
            document,
            output_format="markdown",
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=True,
            favor_precision=True,
        )
        if script_shell:
            main = None
        if main:
            if len(main) > self._settings.html_max_text_chars:
                warnings.append(
                    Warning(
                        code="html_main_content_truncated",
                        message="Основной текст HTML достиг настроенного ограничения.",
                    )
                )
            main = main[: self._settings.html_max_text_chars]
            encoded_main = main.encode()
            if len(encoded_main) > self._settings.inline_max_output_bytes:
                encoded_main = encoded_main[: self._settings.inline_max_output_bytes]
                encoded_main = encoded_main.decode("utf-8", errors="ignore").encode()
                if not any(item.code == "html_main_content_truncated" for item in warnings):
                    warnings.append(
                        Warning(
                            code="html_main_content_truncated",
                            message="Основной текст HTML достиг настроенного ограничения.",
                        )
                    )
            representations.append(
                ParsedRepresentation(
                    representation=ContentRepresentationKind.MARKDOWN,
                    media_type="text/markdown; charset=utf-8",
                    schema_revision="content-html-main-v1",
                    data=encoded_main,
                )
            )
        else:
            warnings.append(
                Warning(
                    code="html_main_content_unavailable",
                    message="Читаемое представление основного текста HTML извлечь не удалось.",
                )
            )

        structure = _extract_structure(root, self._settings, warnings)
        representations.append(
            ParsedRepresentation(
                representation=ContentRepresentationKind.STRUCTURED,
                media_type="application/vnd.web-access.content+json",
                schema_revision="content-html-structure-v1",
                data=bounded_json_bytes(
                    {"schema_revision": "content-html-structure-v1", **structure},
                    self._settings.inline_max_output_bytes,
                ),
            )
        )
        if script_shell:
            hints.append(browser_may_be_required())
        return NativeParserOutput(
            representations=tuple(representations),
            warnings=tuple(warnings),
            hints=tuple(hints),
        )


def _extract_structure(
    root: html.HtmlElement,
    settings: ParserSettings,
    warnings: list[Warning],
) -> dict[str, object]:
    metadata_limit = settings.html_max_metadata_chars
    title = _first_text(root.xpath("//title/text()"), metadata_limit)
    canonical = _first_attribute(
        root.xpath("//link[contains(concat(' ', normalize-space(@rel), ' '), ' canonical ')]"),
        "href",
        metadata_limit,
    )
    description = _first_attribute(
        root.xpath(
            "//meta[translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')="
            "'description']"
        ),
        "content",
        metadata_limit,
    )
    headings = [
        {
            "level": int(element.tag[1]),
            "text": _bounded_text(element.text_content(), metadata_limit),
        }
        for element in root.xpath("//h1|//h2|//h3|//h4|//h5|//h6")[: settings.html_max_headings]
    ]
    links = [
        {
            "href": (element.get("href") or "")[:metadata_limit],
            "text": _bounded_text(element.text_content(), metadata_limit),
        }
        for element in root.xpath("//a[@href]")[: settings.html_max_links]
    ]
    open_graph: dict[str, str] = {}
    for element in root.xpath("//meta[@property and @content]"):
        key = (element.get("property") or "").lower()
        if key in _OG_KEYS and key not in open_graph:
            open_graph[key] = (element.get("content") or "")[:metadata_limit]

    json_ld: list[object] = []
    for element in root.xpath(
        "//script[translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')="
        "'application/ld+json']"
    )[: settings.html_max_jsonld_items]:
        raw_json_ld = element.text or ""
        if len(raw_json_ld) > metadata_limit * 4:
            if not any(item.code == "html_jsonld_oversized" for item in warnings):
                warnings.append(
                    Warning(
                        code="html_jsonld_oversized",
                        message="Слишком большой блок JSON-LD был пропущен.",
                    )
                )
            continue
        try:
            value = json.loads(raw_json_ld)
            json_depth(value, settings.structured_max_depth)
            json_ld.append(value)
        except (ValueError, RecursionError):
            if not any(item.code == "html_jsonld_invalid" for item in warnings):
                warnings.append(
                    Warning(
                        code="html_jsonld_invalid",
                        message="Некорректный или слишком глубокий блок JSON-LD был пропущен.",
                    )
                )
    return {
        "title": title,
        "canonical_url": canonical,
        "description": description,
        "headings": headings,
        "links": links,
        "open_graph": open_graph,
        "json_ld": json_ld,
    }


def _is_script_shell(root: html.HtmlElement) -> bool:
    body = root.find("body")
    if body is None:
        return False
    clone = html.fromstring(html.tostring(body))
    for element in clone.xpath(".//script|.//style|.//noscript"):
        element.drop_tree()
    meaningful_text = _SPACE.sub(" ", clone.text_content()).strip()
    scripts = root.xpath("//script[@src or @type='module' or normalize-space(text())]")
    shell_roots = root.xpath("//*[@id]")
    has_shell_root = any((element.get("id") or "").lower() in _SHELL_IDS for element in shell_roots)
    return not meaningful_text and bool(scripts) and has_shell_root


def _first_text(values: list[str], limit: int) -> str | None:
    return _bounded_text(values[0], limit) if values else None


def _first_attribute(elements: list[html.HtmlElement], name: str, limit: int) -> str | None:
    if not elements:
        return None
    value = elements[0].get(name)
    return value[:limit] if value else None


def _bounded_text(value: str, limit: int) -> str:
    return _SPACE.sub(" ", value).strip()[:limit]
