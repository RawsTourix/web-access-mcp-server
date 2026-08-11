"""Bounded stdlib JSON parser with an application-owned output schema."""

from __future__ import annotations

import json

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


class JsonNativeParser:
    def __init__(self, settings: ParserSettings) -> None:
        self._settings = settings

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="json",
            revision="json-stdlib-v1",
            profile_revision="json-default-v1",
            supported_formats=(ContentFormat.JSON,),
            primary_representation=ContentRepresentationKind.STRUCTURED,
            representation_schema_revision="content-json-v1",
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source
        require_input_bound(data, self._settings.inline_max_input_bytes)
        try:
            value = json.loads(
                data.decode(inspection.encoding or "utf-8-sig"),
                parse_constant=_reject_nonstandard_constant,
            )
        except (LookupError, UnicodeDecodeError, ValueError, RecursionError) as error:
            raise NativeParserError("invalid JSON Content") from error
        json_depth(value, self._settings.structured_max_depth)
        encoded = bounded_json_bytes(
            {"schema_revision": "content-json-v1", "value": value},
            self._settings.inline_max_output_bytes,
        )
        return NativeParserOutput(
            representations=(
                ParsedRepresentation(
                    representation=ContentRepresentationKind.STRUCTURED,
                    media_type="application/vnd.web-access.content+json",
                    schema_revision="content-json-v1",
                    data=encoded,
                ),
            )
        )


def _reject_nonstandard_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")
