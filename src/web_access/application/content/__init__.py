"""Content application contracts."""

from web_access.application.content.models import (
    ContentInspection,
    ContentReadResult,
    ContentRef,
    NativeParseResult,
    NativeParserOutput,
    ParsedRepresentation,
    ParserDescriptor,
)

__all__ = [
    "ContentInspection",
    "ContentReadResult",
    "ContentRef",
    "NativeParseResult",
    "NativeParserOutput",
    "ParsedRepresentation",
    "ParserDescriptor",
]
