from __future__ import annotations

import asyncio
import ctypes
import gc
import os
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from web_access.core.config import ParserSettings
from web_access.infrastructure.content.parser_isolation import (
    ParserChildCrash,
    ParserChildTimeout,
    SubprocessParserExecutor,
)

_TEST_PARSERS = frozenset({"test_crash", "test_echo", "test_sleep"})


class _ReducedIsolationExecutor(SubprocessParserExecutor):
    @property
    def hard_network_isolation(self) -> bool:
        return False


def _executor(root: Path, *, timeout: float) -> _ReducedIsolationExecutor:
    return _ReducedIsolationExecutor(
        ParserSettings(
            child_temp_root=root,
            child_timeout_seconds=timeout,
            child_concurrency=2,
            child_memory_bytes=256 * 1024 * 1024,
        ),
        allowed_parser_ids=_TEST_PARSERS,
        allow_reduced_isolation=True,
        test_mode=True,
    )


def _open_resource_count() -> int:
    proc_fds = Path("/proc/self/fd")
    if proc_fds.is_dir():
        return len(tuple(proc_fds.iterdir()))
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_handle_count = kernel32.GetProcessHandleCount
        get_process_handle_count.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        )
        get_process_handle_count.restype = ctypes.c_int
        count = ctypes.c_ulong()
        if not get_process_handle_count(get_current_process(), ctypes.byref(count)):
            raise OSError(ctypes.get_last_error(), "GetProcessHandleCount failed")
        return count.value
    return 0


@pytest.mark.asyncio
async def test_parser_subprocess_soak_reaps_children_and_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    root = tmp_path / "parser-soak"
    normal = _executor(root, timeout=2)
    timeout_executor = _executor(root, timeout=0.05)
    created: list[asyncio.subprocess.Process] = []
    peak_live = 0
    original_create = asyncio.create_subprocess_exec

    warmup = await normal.execute("test_echo", b"warmup")
    assert warmup.representations[0].data == b"warmup"
    await timeout_executor.start()
    await asyncio.sleep(0.05)
    gc.collect()
    baseline_resources = _open_resource_count()

    async def recording_create(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        nonlocal peak_live
        process = await original_create(*args, **kwargs)
        created.append(process)
        peak_live = max(peak_live, sum(item.returncode is None for item in created))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_create)
    tracemalloc.start()
    baseline_memory, _baseline_peak = tracemalloc.get_traced_memory()
    cycles = 3
    for cycle in range(cycles):
        results = await asyncio.gather(
            normal.execute("test_echo", f"success-{cycle}-a".encode()),
            normal.execute("test_echo", f"success-{cycle}-b".encode()),
        )
        assert [item.representations[0].data for item in results] == [
            f"success-{cycle}-a".encode(),
            f"success-{cycle}-b".encode(),
        ]

        with pytest.raises(ParserChildTimeout):
            await timeout_executor.execute("test_sleep", b"", parameters={"seconds": 5})
        with pytest.raises(ParserChildCrash):
            await normal.execute("test_crash", b"")

        cancelled = asyncio.create_task(
            normal.execute("test_sleep", b"", parameters={"seconds": 5})
        )
        await asyncio.sleep(0.05)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert root.is_dir() and list(root.iterdir()) == []

    started_children = len(created)
    orphan_children = sum(process.returncode is None for process in created)
    all_reaped = all(process.returncode is not None for process in created)
    created.clear()
    await asyncio.sleep(0.05)
    gc.collect()
    current_memory, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    final_resources = _open_resource_count()

    record_property("parser_cycles", cycles)
    record_property("parser_children_started", started_children)
    record_property("parser_peak_live_children", peak_live)
    record_property("parser_orphan_children", orphan_children)
    record_property("parser_resource_delta", final_resources - baseline_resources)
    record_property("parser_memory_delta", current_memory - baseline_memory)
    record_property("parser_peak_traced_bytes", peak_memory)

    assert started_children == cycles * 5
    assert orphan_children == 0
    assert all_reaped
    assert peak_live <= 2
    assert list(root.iterdir()) == []
    assert final_resources <= baseline_resources + 8
    assert current_memory - baseline_memory < 2 * 1024 * 1024
