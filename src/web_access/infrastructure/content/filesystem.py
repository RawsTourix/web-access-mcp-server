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

from web_access.application.common.content_store import StagedBlob, StoredBlob
from web_access.core.config import ContentStoreSettings

_KEY_PATTERN = re.compile(r"^sha256/([0-9a-f]{2})/([0-9a-f]{64})$")
_STAGING_PATTERN = re.compile(r"^staging/(cnt_[0-9a-f]{32})/([0-9a-f]{32})\.part$")
_IDENTITY_PATTERN = re.compile(r"^cnt_[0-9a-f]{32}$")


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
        self._ensure_managed_directory(self._root)
        self._ensure_managed_directory(self._blobs)
        self._ensure_managed_directory(self._blobs / "sha256")
        self._ensure_managed_directory(self._staging)

    def _ensure_managed_directory(self, path: Path) -> None:
        if path.is_symlink():
            raise InvalidStorageKey("managed ContentStore directory cannot be a symbolic link")
        path.mkdir(mode=0o750, exist_ok=True)
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise InvalidStorageKey("managed ContentStore directory is unavailable") from error
        expected = path.absolute()
        if resolved != expected or (resolved != self._root and self._root not in resolved.parents):
            raise InvalidStorageKey("managed ContentStore directory escapes the canonical root")
        if not resolved.is_dir():
            raise InvalidStorageKey("managed ContentStore path is not a directory")

    def _validate_managed_directories(self) -> None:
        for path in (self._root, self._blobs, self._blobs / "sha256", self._staging):
            if path.is_symlink():
                raise InvalidStorageKey("managed ContentStore directory cannot be a symbolic link")
            try:
                resolved = path.resolve(strict=True)
            except OSError as error:
                raise InvalidStorageKey("managed ContentStore directory is unavailable") from error
            expected = path.absolute()
            if resolved != expected or (
                resolved != self._root and self._root not in resolved.parents
            ):
                raise InvalidStorageKey("managed ContentStore directory escapes the canonical root")
            if not resolved.is_dir():
                raise InvalidStorageKey("managed ContentStore path is not a directory")

    def _path_for_key(self, key: str) -> tuple[Path, str]:
        self._validate_managed_directories()
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
        identity = f"cnt_{secrets.token_hex(16)}"
        staged = await self.stage_write(identity, stream)
        try:
            return await self.finalize(staged)
        finally:
            await self.remove_staging(staged.handle)

    def _path_for_staging_handle(self, handle: str) -> Path:
        self._validate_managed_directories()
        match = _STAGING_PATTERN.fullmatch(handle)
        if match is None:
            raise InvalidStorageKey("invalid staging handle")
        path = self._staging / match.group(1) / f"{match.group(2)}.part"
        parent = path.parent.resolve()
        staging_root = self._staging.resolve()
        if staging_root not in parent.parents:
            raise InvalidStorageKey("staging handle escapes managed root")
        return path

    async def stage_write(self, identity: str, stream: AsyncIterable[bytes]) -> StagedBlob:
        await self.start()
        if _IDENTITY_PATTERN.fullmatch(identity) is None:
            raise InvalidStorageKey("invalid staging identity")
        handle_key = f"staging/{identity}/{secrets.token_hex(16)}.part"
        staging = self._path_for_staging_handle(handle_key)
        await asyncio.to_thread(staging.parent.mkdir, mode=0o750, parents=True, exist_ok=True)
        if staging.parent.is_symlink():
            raise InvalidStorageKey("staging identity directory cannot be a symbolic link")
        digest = hashlib.sha256()
        size = 0
        handle: BinaryIO | None = None
        completed = False
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
            completed = True
            return StagedBlob(handle=handle_key, sha256=digest.hexdigest(), size=size)
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)
            if not completed:
                await asyncio.to_thread(self._safe_unlink_staging, staging)

    async def stat_staging(self, handle: str) -> StagedBlob | None:
        path = self._path_for_staging_handle(handle)
        if path.is_symlink() or not await asyncio.to_thread(path.is_file):
            return None
        digest = hashlib.sha256()
        size = 0
        file_handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(file_handle.read, self._chunk_size):
                digest.update(chunk)
                size += len(chunk)
        finally:
            await asyncio.to_thread(file_handle.close)
        return StagedBlob(handle=handle, sha256=digest.hexdigest(), size=size)

    async def finalize(self, staged: StagedBlob) -> StoredBlob:
        staging = self._path_for_staging_handle(staged.handle)
        observed = await self.stat_staging(staged.handle)
        key = f"sha256/{staged.sha256[:2]}/{staged.sha256}"
        target, _ = self._path_for_key(key)
        if observed is None:
            if await asyncio.to_thread(self._verify_blob, target, staged.sha256, staged.size):
                return StoredBlob(key=key, sha256=staged.sha256, size=staged.size)
            raise FileNotFoundError(staged.handle)
        if observed.sha256 != staged.sha256 or observed.size != staged.size:
            raise OSError("staging blob failed integrity verification")
        await asyncio.to_thread(target.parent.mkdir, mode=0o750, parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(os.link, staging, target)
        except FileExistsError:
            if not await asyncio.to_thread(self._verify_blob, target, staged.sha256, staged.size):
                raise OSError(
                    "existing content-addressed blob failed integrity verification"
                ) from None
        await asyncio.to_thread(self._safe_unlink_staging, staging)
        return StoredBlob(key=key, sha256=staged.sha256, size=staged.size)

    async def remove_staging(self, handle: str) -> bool:
        path = self._path_for_staging_handle(handle)
        if path.is_symlink():
            raise InvalidStorageKey("symbolic-link staging objects are not trusted")
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return False
        await asyncio.to_thread(self._prune_staging_parent, path.parent)
        return True

    def _safe_unlink_staging(self, path: Path) -> None:
        """Never follow a replaced staging base while cleaning our temporary file."""

        try:
            self._validate_managed_directories()
        except (InvalidStorageKey, OSError):
            return
        path.unlink(missing_ok=True)
        self._prune_staging_parent(path.parent)

    def _prune_staging_parent(self, path: Path) -> None:
        if path == self._staging or path.parent != self._staging:
            return
        try:
            path.rmdir()
        except (FileNotFoundError, OSError):
            return

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
        await asyncio.to_thread(self._validate_managed_directories)
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in await asyncio.to_thread(lambda: list(self._staging.glob("**/*.part"))):
            if path.is_symlink() or not path.is_file():
                continue
            if (await asyncio.to_thread(path.stat)).st_mtime <= cutoff:
                await asyncio.to_thread(path.unlink, missing_ok=True)
                removed += 1
        return removed

    async def probe(self) -> bool:
        """Check existing managed directories without creating or repairing them."""

        try:
            await asyncio.to_thread(self._validate_managed_directories)
            return await asyncio.to_thread(
                lambda: all(
                    os.access(path, os.R_OK | os.W_OK | os.X_OK)
                    for path in (
                        self._root,
                        self._blobs,
                        self._blobs / "sha256",
                        self._staging,
                    )
                )
            )
        except Exception:
            # A health check is a total fail-closed query. Cancellation remains
            # observable because asyncio.CancelledError is a BaseException.
            return False
