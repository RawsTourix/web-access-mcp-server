from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import AsyncIterator

import pytest

from web_access.core.config import ContentStoreSettings
from web_access.infrastructure.content import FilesystemContentStore, InvalidStorageKey


async def _chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _redirect_directory(link, target) -> None:
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    process = await asyncio.create_subprocess_exec(
        os.environ["COMSPEC"],
        "/d",
        "/c",
        "mklink",
        "/J",
        str(link),
        str(target),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout, stderr)


@pytest.mark.asyncio
async def test_stream_roundtrip_hash_stat_exists_and_remove(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path, chunk_size=4096))
    data = b"a" * 5000 + b"b" * 5000
    blob = await store.write_stream(_chunks(data[:123], data[123:7000], data[7000:]))
    assert blob.sha256 == hashlib.sha256(data).hexdigest()
    assert blob.size == len(data)
    assert blob.key == f"sha256/{blob.sha256[:2]}/{blob.sha256}"
    assert await store.exists(blob.key)
    assert await store.stat(blob.key) == blob
    assert b"".join([chunk async for chunk in store.open_stream(blob.key)]) == data
    assert await store.remove(blob.key)
    assert not await store.remove(blob.key)
    assert await store.stat(blob.key) is None
    with pytest.raises(FileNotFoundError):
        _ = [chunk async for chunk in store.open_stream(blob.key)]


@pytest.mark.asyncio
async def test_concurrent_same_content_physically_deduplicates(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path, chunk_size=4096))
    data = b"same-content" * 10_000
    results = await asyncio.gather(
        *(store.write_stream(_chunks(data[:5000], data[5000:])) for _ in range(8))
    )
    assert len({result.key for result in results}) == 1
    assert len(list((tmp_path / "blobs" / "sha256" / results[0].sha256[:2]).iterdir())) == 1
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_failed_stream_never_publishes_and_cleans_staging(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))

    async def failing_stream() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("synthetic stream failure")

    with pytest.raises(RuntimeError, match="synthetic"):
        await store.write_stream(failing_stream())
    assert list((tmp_path / "staging").iterdir()) == []
    assert list((tmp_path / "blobs" / "sha256").iterdir()) == []


@pytest.mark.asyncio
async def test_cleanup_abandoned_staging_and_non_mutating_probe(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
    await store.start()
    abandoned = tmp_path / "staging" / "abandoned.part"
    abandoned.write_bytes(b"partial")
    os.utime(abandoned, (1, 1))
    before = set(tmp_path.rglob("*"))
    assert await store.probe()
    assert set(tmp_path.rglob("*")) == before
    assert await store.cleanup_staging(0) == 1
    assert not abandoned.exists()


@pytest.mark.asyncio
async def test_probe_does_not_recreate_missing_managed_directory(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
    await store.start()
    staging = tmp_path / "staging"
    shutil.rmtree(staging)

    assert not await store.probe()
    assert not staging.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("managed_base", ["blobs", "sha256", "staging"])
async def test_probe_rejects_managed_directory_redirects(tmp_path, managed_base: str) -> None:
    root = tmp_path / "managed"
    outside = tmp_path / f"outside-{managed_base}"
    store = FilesystemContentStore(ContentStoreSettings(root=root))
    await store.start()
    outside.mkdir()
    if managed_base == "blobs":
        link = root / "blobs"
    elif managed_base == "sha256":
        link = root / "blobs" / "sha256"
    else:
        link = root / "staging"
    shutil.rmtree(link)
    await _redirect_directory(link, outside)

    assert not await store.probe()
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "/absolute/path",
        "sha256/aa/../escape",
        f"sha256/ff/{'a' * 64}",
        f"sha256/aa/{'A' * 64}",
    ],
)
async def test_rejects_noncanonical_and_escape_keys(tmp_path, key: str) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
    await store.start()
    with pytest.raises(InvalidStorageKey):
        await store.exists(key)


@pytest.mark.asyncio
async def test_existing_corrupt_blob_is_not_silently_reused(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
    data = b"expected-content"
    digest = hashlib.sha256(data).hexdigest()
    target = tmp_path / "blobs" / "sha256" / digest[:2] / digest
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")
    with pytest.raises(OSError, match="integrity"):
        await store.write_stream(_chunks(data))
    assert target.read_bytes() == b"corrupt"
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_symbolic_link_blob_is_never_followed_or_removed(tmp_path) -> None:
    store = FilesystemContentStore(ContentStoreSettings(root=tmp_path))
    await store.start()
    data = b"outside-content"
    digest = hashlib.sha256(data).hexdigest()
    key = f"sha256/{digest[:2]}/{digest}"
    shard = tmp_path / "blobs" / "sha256" / digest[:2]

    if os.name == "nt":
        outside_directory = tmp_path / "outside-directory"
        outside_directory.mkdir()
        process = await asyncio.create_subprocess_exec(
            os.environ["COMSPEC"],
            "/d",
            "/c",
            "mklink",
            "/J",
            str(shard),
            str(outside_directory),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, (stdout, stderr)
        with pytest.raises(InvalidStorageKey, match="escapes"):
            await store.write_stream(_chunks(data))
        assert list(outside_directory.iterdir()) == []
        assert list((tmp_path / "staging").iterdir()) == []
        return

    target = shard / digest
    shard.mkdir(parents=True)
    outside_file = tmp_path / "outside"
    outside_file.write_bytes(data)
    target.symlink_to(outside_file)

    assert await store.stat(key) is None
    with pytest.raises(FileNotFoundError):
        _ = [chunk async for chunk in store.open_stream(key)]
    with pytest.raises(InvalidStorageKey, match="symbolic-link"):
        await store.remove(key)
    with pytest.raises(OSError, match="integrity"):
        await store.write_stream(_chunks(data))
    assert outside_file.read_bytes() == data


@pytest.mark.asyncio
@pytest.mark.parametrize("managed_base", ["blobs", "sha256", "staging"])
@pytest.mark.parametrize("operation", ["write", "open", "stat", "remove", "cleanup"])
async def test_managed_directory_redirects_are_never_followed(
    tmp_path, managed_base: str, operation: str
) -> None:
    root = tmp_path / "managed"
    outside = tmp_path / f"outside-{managed_base}-{operation}"
    root.mkdir()
    outside.mkdir()
    if managed_base == "blobs":
        link = root / "blobs"
    elif managed_base == "sha256":
        (root / "blobs").mkdir()
        link = root / "blobs" / "sha256"
    else:
        (root / "blobs" / "sha256").mkdir(parents=True)
        link = root / "staging"
    await _redirect_directory(link, outside)

    store = FilesystemContentStore(ContentStoreSettings(root=root))
    key = f"sha256/00/{'0' * 64}"
    with pytest.raises(InvalidStorageKey, match="managed ContentStore"):
        if operation == "write":
            await store.write_stream(_chunks(b"must-not-escape"))
        elif operation == "open":
            _ = [chunk async for chunk in store.open_stream(key)]
        elif operation == "stat":
            await store.stat(key)
        elif operation == "remove":
            await store.remove(key)
        else:
            await store.cleanup_staging(0)
    assert list(outside.iterdir()) == []
