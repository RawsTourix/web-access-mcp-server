"""Hardened bounded XML parser with no entity or network resolution."""

from __future__ import annotations

from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

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
    ParserDepthLimitExceeded,
    bounded_json_bytes,
    require_input_bound,
)


class XmlNativeParser:
    def __init__(self, settings: ParserSettings) -> None:
        self._settings = settings

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="xml",
            revision="xml-defused-v1",
            profile_revision="xml-default-v1",
            supported_formats=(ContentFormat.XML,),
            primary_representation=ContentRepresentationKind.STRUCTURED,
            representation_schema_revision="content-xml-v1",
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source, inspection
        require_input_bound(data, self._settings.inline_max_input_bytes)
        if b"<!doctype" in data.lower():
            raise NativeParserError("XML DTD declarations are not allowed")
        try:
            root = ElementTree.fromstring(data)
        except (DefusedXmlException, ParseError) as error:
            raise NativeParserError("unsafe or invalid XML Content") from error
        nodes = [0]
        tree = _element(
            root,
            depth=1,
            max_depth=self._settings.structured_max_depth,
            max_nodes=self._settings.structured_max_nodes,
            nodes=nodes,
        )
        encoded = bounded_json_bytes(
            {"schema_revision": "content-xml-v1", "root": tree},
            self._settings.inline_max_output_bytes,
        )
        return NativeParserOutput(
            representations=(
                ParsedRepresentation(
                    representation=ContentRepresentationKind.STRUCTURED,
                    media_type="application/vnd.web-access.content+json",
                    schema_revision="content-xml-v1",
                    data=encoded,
                ),
            )
        )


def _element(
    element: Element,
    *,
    depth: int,
    max_depth: int,
    max_nodes: int,
    nodes: list[int],
) -> dict[str, object]:
    if depth > max_depth:
        raise ParserDepthLimitExceeded("XML exceeds depth limit")
    nodes[0] += 1
    if nodes[0] > max_nodes:
        raise ParserDepthLimitExceeded("XML exceeds node limit")
    return {
        "tag": str(element.tag),
        "attributes": {str(key): value for key, value in sorted(element.attrib.items())},
        "text": element.text or "",
        "tail": element.tail or "",
        "children": [
            _element(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                max_nodes=max_nodes,
                nodes=nodes,
            )
            for child in element
        ],
    }
