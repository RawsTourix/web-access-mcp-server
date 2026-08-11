"""Content application contracts."""

from web_access.application.content.models import (
    ContentInspection,
    ContentReadResult,
    ContentRef,
    NativeParseResult,
    ParserDescriptor,
)

__all__ = [
    "ContentInspection",
    "ContentReadResult",
    "ContentRef",
    "NativeParseResult",
    "ParserDescriptor",
]
