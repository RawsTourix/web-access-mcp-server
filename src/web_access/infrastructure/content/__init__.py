"""Content storage adapters."""

from web_access.infrastructure.content.cursor import HmacContentCursorCodec, InvalidContentCursor
from web_access.infrastructure.content.filesystem import (
    FilesystemContentStore,
    InvalidStorageKey,
)
from web_access.infrastructure.content.identifier import (
    ContentIdentificationRegistry,
    IdentificationDescriptor,
    RegistryContentIdentifier,
    default_identification_registry,
)
from web_access.infrastructure.content.parser_isolation import SubprocessParserExecutor

__all__ = [
    "ContentIdentificationRegistry",
    "FilesystemContentStore",
    "HmacContentCursorCodec",
    "IdentificationDescriptor",
    "InvalidContentCursor",
    "InvalidStorageKey",
    "RegistryContentIdentifier",
    "SubprocessParserExecutor",
    "default_identification_registry",
]
