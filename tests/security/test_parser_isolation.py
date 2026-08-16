from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from web_access.core.config import ParserSettings
from web_access.infrastructure.content import parser_isolation
from web_access.infrastructure.content.parser_isolation import (
    ParserChildCrash,
    ParserChildTimeout,
    ParserIsolationError,
    ParserIsolationUnavailable,
    SubprocessParserExecutor,
)

_TEST_PARSERS = frozenset(
    {
        "test_crash",
        "test_echo",
        "test_environment",
        "test_sleep",
    }
)


class ReducedDevelopmentExecutor(SubprocessParserExecutor):
    """Exercise process controls on dev platforms; Docker proves hard network isolation."""

    @property
    def hard_network_isolation(self) -> bool:
        return False


class HardPreflightExecutor(SubprocessParserExecutor):
    """Exercise the hard-isolation startup path on every development platform."""

    preflight_reaped = False

    @property
    def hard_network_isolation(self) -> bool:
        return True

    async def _terminate_and_reap(self, process: asyncio.subprocess.Process) -> None:
        await super()._terminate_and_reap(process)
        self.preflight_reaped = process.returncode is not None


def _executor(
    root: Path,
    *,
    timeout: float = 2.0,
    concurrency: int = 2,
    output_bytes: int = 1024 * 1024,
) -> ReducedDevelopmentExecutor:
    return ReducedDevelopmentExecutor(
        ParserSettings(
            child_temp_root=root,
            child_timeout_seconds=timeout,
            child_concurrency=concurrency,
            child_output_bytes=output_bytes,
            child_memory_bytes=256 * 1024 * 1024,
        ),
        allowed_parser_ids=_TEST_PARSERS,
        allow_reduced_isolation=True,
        test_mode=True,
    )


def _hard_executor(root: Path) -> HardPreflightExecutor:
    return HardPreflightExecutor(
        ParserSettings(
            child_temp_root=root,
            child_memory_bytes=256 * 1024 * 1024,
        ),
        allowed_parser_ids=frozenset({"test_echo"}),
        test_mode=True,
    )


@pytest.mark.asyncio
async def test_start_runs_disposable_sandbox_preflight_once_with_minimal_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _hard_executor(tmp_path / "parser-root")
    calls: list[dict[str, str]] = []

    class CompletedProcess:
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def create_process(*_command: str, **options: object) -> CompletedProcess:
        environment = options["env"]
        assert isinstance(environment, dict)
        calls.append(environment)
        return CompletedProcess()

    monkeypatch.setenv("WEB_ACCESS_DATABASE__URL", "postgresql://secret")
    monkeypatch.setenv("WEB_ACCESS_REDIS__URL", "redis://secret")
    monkeypatch.setattr(parser_isolation.asyncio, "create_subprocess_exec", create_process)

    await executor.start()
    await executor.start()

    assert len(calls) == 1
    assert "WEB_ACCESS_DATABASE__URL" not in calls[0]
    assert "WEB_ACCESS_REDIS__URL" not in calls[0]
    assert executor._started


@pytest.mark.asyncio
async def test_sandbox_preflight_failure_keeps_executor_unstarted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _hard_executor(tmp_path / "parser-root")
    monkeypatch.setattr(parser_isolation, "_SANDBOX_PREFLIGHT_BOOTSTRAP", "raise SystemExit(23)")

    with pytest.raises(ParserIsolationUnavailable, match="status 23"):
        await executor.start()

    assert not executor._started


@pytest.mark.asyncio
async def test_sandbox_preflight_spawn_failure_is_normalized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _hard_executor(tmp_path / "parser-root")

    async def fail_spawn(*_command: str, **_options: object) -> None:
        raise OSError("forced spawn failure")

    monkeypatch.setattr(parser_isolation.asyncio, "create_subprocess_exec", fail_spawn)

    with pytest.raises(ParserIsolationUnavailable, match="could not start"):
        await executor.start()

    assert not executor._started


@pytest.mark.asyncio
async def test_sandbox_preflight_timeout_terminates_and_reaps_child(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _hard_executor(tmp_path / "parser-root")
    monkeypatch.setattr(
        parser_isolation,
        "_SANDBOX_PREFLIGHT_BOOTSTRAP",
        "import time;time.sleep(60)",
    )
    monkeypatch.setattr(parser_isolation, "_SANDBOX_PREFLIGHT_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(ParserIsolationUnavailable, match="timed out"):
        await executor.start()

    assert executor.preflight_reaped
    assert not executor._started


@pytest.mark.asyncio
async def test_sandbox_preflight_cancellation_terminates_and_reaps_child(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _hard_executor(tmp_path / "parser-root")
    monkeypatch.setattr(
        parser_isolation,
        "_SANDBOX_PREFLIGHT_BOOTSTRAP",
        "import time;time.sleep(60)",
    )

    task = asyncio.create_task(executor.start())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert executor.preflight_reaped
    assert not executor._started


@pytest.mark.asyncio
async def test_json_protocol_roundtrip_uses_private_temp_and_cleans_success(tmp_path) -> None:
    root = tmp_path / "parser-root"
    executor = _executor(root)
    result = await executor.execute("test_echo", b"bounded input")

    assert result.representations[0].data == b"bounded input"
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_child_receives_no_parent_credentials(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensitive = {
        "WEB_ACCESS_DATABASE__URL": "postgresql://secret",
        "WEB_ACCESS_REDIS__URL": "redis://secret",
        "WEB_ACCESS_AUTH__PRINCIPALS": "bearer-secret",
        "WEB_ACCESS_SEARCH__YANDEX__API_KEY": "provider-secret",
        "WEB_ACCESS_CONTENT_STORE__ROOT": "private-content-root",
    }
    for key, value in sensitive.items():
        monkeypatch.setenv(key, value)

    result = await _executor(tmp_path / "parser-root").execute("test_environment", b"")
    observed = json.loads(result.representations[0].data)
    assert observed == dict.fromkeys(sensitive, False)


@pytest.mark.asyncio
async def test_timeout_terminates_reaps_and_cleans_child(tmp_path) -> None:
    root = tmp_path / "parser-root"
    executor = _executor(root, timeout=0.05)
    with pytest.raises(ParserChildTimeout):
        await executor.execute("test_sleep", b"", parameters={"seconds": 5})
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_crash_and_parent_cancellation_cleanup_private_temp(tmp_path) -> None:
    root = tmp_path / "parser-root"
    executor = _executor(root)
    with pytest.raises(ParserChildCrash):
        await executor.execute("test_crash", b"")
    assert list(root.iterdir()) == []

    task = asyncio.create_task(executor.execute("test_sleep", b"", parameters={"seconds": 5}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_output_and_parser_allowlist_are_enforced(tmp_path) -> None:
    root = tmp_path / "parser-root"
    executor = _executor(root, output_bytes=4096)
    with pytest.raises(ParserIsolationError):
        await executor.execute("not_allowlisted", b"")
    with pytest.raises(ParserIsolationError):
        await executor.execute("test_echo", b"x" * 5000)
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_concurrency_limit_and_stale_reaper_are_bounded(tmp_path) -> None:
    root = tmp_path / "parser-root"
    root.mkdir()
    stale = root / "parser-stale"
    stale.mkdir()
    unrelated = root / "keep-me"
    unrelated.mkdir()
    old = time.time() - 7200
    os.utime(stale, (old, old))
    executor = _executor(root, concurrency=1)

    started = time.monotonic()
    await asyncio.gather(
        executor.execute("test_sleep", b"", parameters={"seconds": 0.15}),
        executor.execute("test_sleep", b"", parameters={"seconds": 0.15}),
    )
    elapsed = time.monotonic() - started

    assert elapsed >= 0.25
    assert not stale.exists()
    assert unrelated.exists()
