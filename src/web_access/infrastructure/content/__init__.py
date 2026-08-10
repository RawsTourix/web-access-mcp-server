"""Content storage adapters."""

from web_access.infrastructure.content.filesystem import (
    FilesystemContentStore,
    InvalidStorageKey,
)

__all__ = ["FilesystemContentStore", "InvalidStorageKey"]
