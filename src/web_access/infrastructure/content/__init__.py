"""Content storage adapters."""

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

__all__ = [
    "ContentIdentificationRegistry",
    "FilesystemContentStore",
    "IdentificationDescriptor",
    "InvalidStorageKey",
    "RegistryContentIdentifier",
    "default_identification_registry",
]
