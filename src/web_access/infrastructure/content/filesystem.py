"""Streaming, content-addressed filesystem ContentStore adapter."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import time
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from typing import BinaryIO

from web_access.application.common.content_store import StoredBlob
from web_access.core.config import ContentStoreSettings

_KEY_PATTERN = re.compile(r"^sha256/([0-9a-f]{2})/([0-9a-f]{64})$")


class InvalidStorageKey(ValueError):
    pass


class FilesystemContentStore:
    def __init__(self, settings: ContentStoreSettings) -> None:
        self._root = settings.root.resolve()
        self._blobs = self._root / "blobs"
        self._staging = self._root / "staging"
        self._chunk_size = settings.chunk_size

    async def start(self) -> None:
        await asyncio.to_thread(self._initialize_directories)

    def _initialize_directories(self) -> None:
        self._root.mkdir(mode=0o750, parents=True, exist_ok=True)
        self._blobs.mkdir(mode=0o750, exist_ok=True)
        (self._blobs / "sha256").mkdir(mode=0o750, exist_ok=True)
        self._staging.mkdir(mode=0o750, exist_ok=True)

    def _path_for_key(self, key: str) -> tuple[Path, str]:
        match = _KEY_PATTERN.fullmatch(key)
        if match is None or match.group(1) != match.group(2)[:2]:
            raise InvalidStorageKey("storage key is not a canonical SHA-256 key")
        path = self._blobs / key
        resolved_parent = path.parent.resolve()
        allowed = (self._blobs / "sha256").resolve()
        if resolved_parent != allowed and allowed not in resolved_parent.parents:
            raise InvalidStorageKey("storage key escapes the managed blob root")
        return path, match.group(2)

    async def write_stream(self, stream: AsyncIterable[bytes]) -> StoredBlob:
        await self.start()
        staging = self._staging / f"{secrets.token_hex(16)}.part"
        digest = hashlib.sha256()
        size = 0
        handle: BinaryIO | None = None
        try:
            handle = await asyncio.to_thread(staging.open, "xb")
            async for chunk in stream:
                if not isinstance(chunk, bytes):
                    raise TypeError("ContentStore stream chunks must be bytes")
                if not chunk:
                    continue
                digest.update(chunk)
                size += len(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(handle.close)
            handle = None
            sha256 = digest.hexdigest()
            key = f"sha256/{sha256[:2]}/{sha256}"
            target, _ = self._path_for_key(key)
            await asyncio.to_thread(target.parent.mkdir, mode=0o750, parents=True, exist_ok=True)
            if await asyncio.to_thread(target.exists):
                if not await asyncio.to_thread(self._verify_blob, target, sha256, size):
                    raise OSError("existing content-addressed blob failed integrity verification")
                await asyncio.to_thread(staging.unlink, missing_ok=True)
            else:
                await asyncio.to_thread(os.replace, staging, target)
            return StoredBlob(key=key, sha256=sha256, size=size)
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(staging.unlink, missing_ok=True)

    def _verify_blob(self, path: Path, expected_hash: str, expected_size: int) -> bool:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(self._chunk_size):
                digest.update(chunk)
        return digest.hexdigest() == expected_hash

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        path, _ = self._path_for_key(key)
        if path.is_symlink() or not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, self._chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def stat(self, key: str) -> StoredBlob | None:
        path, sha256 = self._path_for_key(key)
        if path.is_symlink() or not await asyncio.to_thread(path.is_file):
            return None
        size = (await asyncio.to_thread(path.stat)).st_size
        return StoredBlob(key=key, sha256=sha256, size=size)

    async def exists(self, key: str) -> bool:
        return await self.stat(key) is not None

    async def remove(self, key: str) -> bool:
        path, _ = self._path_for_key(key)
        if path.is_symlink():
            raise InvalidStorageKey("symbolic-link blobs are not trusted")
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return False
        return True

    async def cleanup_staging(self, older_than_seconds: float) -> int:
        if older_than_seconds < 0:
            raise ValueError("staging cleanup age cannot be negative")
        if not await asyncio.to_thread(self._staging.is_dir):
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in await asyncio.to_thread(lambda: list(self._staging.glob("*.part"))):
            if path.is_symlink() or not path.is_file():
                continue
            if (await asyncio.to_thread(path.stat)).st_mtime <= cutoff:
                await asyncio.to_thread(path.unlink, missing_ok=True)
                removed += 1
        return removed

    async def probe(self) -> bool:
        """Check existing root capabilities without a mutating health write."""

        try:
            return bool(
                await asyncio.to_thread(self._root.is_dir)
                and await asyncio.to_thread(self._blobs.is_dir)
                and await asyncio.to_thread(self._staging.is_dir)
                and os.access(self._root, os.R_OK | os.W_OK | os.X_OK)
            )
        except OSError:
            return False
