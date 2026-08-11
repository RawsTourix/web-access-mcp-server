"""Bounded plain-text decoding and UTF-8 normalization."""

from __future__ import annotations

import codecs

from charset_normalizer import from_bytes

from web_access.application.common.hints import Warning
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
    ParserOutputLimitExceeded,
    require_input_bound,
)


class TextNativeParser:
    def __init__(self, settings: ParserSettings) -> None:
        self._settings = settings

    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            capability="text",
            revision="text-parser-v1",
            profile_revision="text-default-v1",
            supported_formats=(ContentFormat.TEXT,),
            primary_representation=ContentRepresentationKind.TEXT,
            representation_schema_revision="content-text-v1",
        )

    async def parse(
        self, source: ContentObject, inspection: ContentInspection, data: bytes
    ) -> NativeParserOutput:
        del source
        require_input_bound(data, self._settings.inline_max_input_bytes)
        text, inferred = _decode(data, inspection.encoding)
        encoded = text.encode()
        if len(encoded) > self._settings.inline_max_output_bytes:
            raise ParserOutputLimitExceeded("normalized text exceeds output limit")
        warnings = (
            (
                Warning(
                    code="encoding_inferred",
                    message="Text encoding was inferred from bounded byte evidence.",
                ),
            )
            if inferred
            else ()
        )
        return NativeParserOutput(
            representations=(
                ParsedRepresentation(
                    representation=ContentRepresentationKind.TEXT,
                    media_type="text/plain; charset=utf-8",
                    schema_revision="content-text-v1",
                    data=encoded,
                ),
            ),
            warnings=warnings,
        )


def _decode(data: bytes, observed_encoding: str | None) -> tuple[str, bool]:
    candidates: list[str] = []
    if observed_encoding:
        candidates.append(observed_encoding)
    if data.startswith(codecs.BOM_UTF8):
        candidates.append("utf-8-sig")
    elif data.startswith(codecs.BOM_UTF16_LE):
        candidates.append("utf-16-le")
    elif data.startswith(codecs.BOM_UTF16_BE):
        candidates.append("utf-16-be")
    candidates.append("utf-8")
    for encoding in dict.fromkeys(candidates):
        try:
            return data.decode(encoding), False
        except (LookupError, UnicodeDecodeError):
            continue
    match = from_bytes(data).best()
    if match is None:
        raise NativeParserError("unable to decode plain text")
    return str(match), True
