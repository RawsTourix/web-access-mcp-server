"""Content application contracts."""

from web_access.application.content.isolation import (
    IsolatedParserRequest,
    IsolatedParserResult,
    IsolatedRepresentation,
)
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
    "IsolatedParserRequest",
    "IsolatedParserResult",
    "IsolatedRepresentation",
    "NativeParseResult",
    "NativeParserOutput",
    "ParsedRepresentation",
    "ParserDescriptor",
]
