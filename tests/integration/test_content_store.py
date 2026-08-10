from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator

import pytest

from web_access.core.config import ContentStoreSettings
from web_access.infrastructure.content import FilesystemContentStore, InvalidStorageKey


async def _chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


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
    before = set(tmp_path.rglob("*"))
    assert await store.probe()
    assert set(tmp_path.rglob("*")) == before
    assert await store.cleanup_staging(0) == 1
    assert not abandoned.exists()


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
