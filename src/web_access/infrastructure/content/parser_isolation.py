"""Fresh-process bounded parser executor with fail-closed Linux network isolation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from pydantic import JsonValue

from web_access.application.content.isolation import (
    IsolatedParserRequest,
    IsolatedParserResult,
)
from web_access.application.content.models import NativeParserOutput, ParsedRepresentation
from web_access.core.config import ParserSettings

_BOOTSTRAP: Final = (
    "import runpy,sys;"
    "sys.path.insert(0,sys.argv.pop(1));"
    "runpy.run_module('web_access.workers.parser_once',run_name='__main__',alter_sys=True)"
)


class ParserIsolationError(RuntimeError):
    code = "parser_isolation_error"


class ParserIsolationUnavailable(ParserIsolationError):
    code = "parser_isolation_unavailable"


class ParserChildTimeout(ParserIsolationError):
    code = "parser_child_timeout"


class ParserChildCrash(ParserIsolationError):
    code = "parser_child_crash"


class ParserChildOutputError(ParserIsolationError):
    code = "parser_child_output_invalid"


class IsolatedParserFailure(ParserIsolationError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SubprocessParserExecutor:
    def __init__(
        self,
        settings: ParserSettings,
        *,
        allowed_parser_ids: frozenset[str],
        allow_reduced_isolation: bool = False,
        test_mode: bool = False,
    ) -> None:
        if not allowed_parser_ids:
            raise ValueError("isolated parser allowlist cannot be empty")
        self._settings = settings
        self._allowed_parser_ids = allowed_parser_ids
        self._allow_reduced_isolation = allow_reduced_isolation
        self._test_mode = test_mode
        self._semaphore = asyncio.Semaphore(settings.child_concurrency)
        self._start_lock = asyncio.Lock()
        self._started = False
        self._source_root = Path(__file__).resolve().parents[3]

    @property
    def hard_network_isolation(self) -> bool:
        return sys.platform.startswith("linux")

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                return
            root = self._settings.child_temp_root.resolve()
            await asyncio.to_thread(root.mkdir, mode=0o700, parents=True, exist_ok=True)
            await self._cleanup_stale(root)
            if self.hard_network_isolation:
                unshare = self._settings.linux_unshare_path
                if not unshare.is_file():
                    raise ParserIsolationUnavailable("Linux unshare executable is unavailable")
            elif not self._allow_reduced_isolation:
                raise ParserIsolationUnavailable(
                    "hard parser network isolation is unavailable on this development platform"
                )
            self._started = True

    async def execute(
        self,
        parser_id: str,
        data: bytes,
        *,
        parameters: dict[str, JsonValue] | None = None,
    ) -> NativeParserOutput:
        if parser_id not in self._allowed_parser_ids:
            raise ParserIsolationError("isolated parser ID is not allowlisted")
        input_limit = (
            self._settings.pdf_max_bytes
            if parser_id == "pdf"
            else self._settings.inline_max_input_bytes
        )
        if len(data) > input_limit:
            raise ParserIsolationError("isolated parser input exceeds configured limit")
        await self.start()
        async with self._semaphore:
            return await self._execute_one(parser_id, data, parameters or {})

    async def _execute_one(
        self, parser_id: str, data: bytes, parameters: dict[str, JsonValue]
    ) -> NativeParserOutput:
        root = self._settings.child_temp_root.resolve()
        work = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="parser-", dir=root))
        await asyncio.to_thread(os.chmod, work, 0o700)
        process: asyncio.subprocess.Process | None = None
        try:
            input_path = work / "input.bin"
            request_path = work / "request.json"
            result_path = work / "result.json"
            await asyncio.to_thread(input_path.write_bytes, data)
            await asyncio.to_thread(os.chmod, input_path, 0o600)
            request = IsolatedParserRequest(
                parser_id=parser_id,
                max_input_bytes=(
                    self._settings.pdf_max_bytes
                    if parser_id == "pdf"
                    else self._settings.inline_max_input_bytes
                ),
                max_output_bytes=self._settings.child_output_bytes,
                cpu_seconds=self._settings.child_cpu_seconds,
                memory_bytes=self._settings.child_memory_bytes,
                open_files=self._settings.child_open_files,
                processes=self._settings.child_processes,
                parameters=parameters,
            )
            payload = request.model_dump_json().encode()
            if len(payload) > 64 * 1024:
                raise ParserIsolationError("isolated parser request exceeds control bound")
            await asyncio.to_thread(request_path.write_bytes, payload)
            await asyncio.to_thread(os.chmod, request_path, 0o600)
            command = self._command(request_path, result_path)
            if os.name == "nt":
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(work),
                    env=self._minimal_environment(work),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(work),
                    env=self._minimal_environment(work),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
            try:
                async with asyncio.timeout(self._settings.child_timeout_seconds):
                    return_code = await process.wait()
            except TimeoutError as error:
                await self._terminate_and_reap(process)
                raise ParserChildTimeout("isolated parser exceeded wall timeout") from error
            except asyncio.CancelledError:
                await self._terminate_and_reap(process)
                raise
            if return_code != 0:
                raise ParserChildCrash(f"isolated parser exited with status {return_code}")
            return await self._read_result(result_path)
        finally:
            if process is not None and process.returncode is None:
                await self._terminate_and_reap(process)
            await asyncio.to_thread(self._remove_private_workdir, root, work)

    def _command(self, request_path: Path, result_path: Path) -> tuple[str, ...]:
        python = sys.executable
        worker = (
            python,
            "-I",
            "-c",
            _BOOTSTRAP,
            str(self._source_root),
            str(request_path),
            str(result_path),
        )
        if not self.hard_network_isolation:
            return worker
        return (
            str(self._settings.linux_unshare_path),
            "--user",
            "--map-root-user",
            "--net",
            *worker,
        )

    def _minimal_environment(self, work: Path) -> dict[str, str]:
        if os.name == "nt":
            system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
            environment = {
                "SYSTEMROOT": system_root,
                "WINDIR": system_root,
                "TEMP": str(work),
                "TMP": str(work),
                "PYTHONIOENCODING": "utf-8",
            }
        else:
            environment = {
                "HOME": str(work),
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "TMPDIR": str(work),
                "PYTHONIOENCODING": "utf-8",
            }
        if self._test_mode:
            environment["WEB_ACCESS_PARSER_TEST_MODE"] = "1"
        return environment

    async def _read_result(self, path: Path) -> NativeParserOutput:
        try:
            size = (await asyncio.to_thread(path.stat)).st_size
            if size > self._settings.child_output_bytes:
                raise ParserChildOutputError("isolated parser result exceeds output bound")
            payload = await asyncio.to_thread(path.read_bytes)
            result = IsolatedParserResult.model_validate_json(payload)
        except ParserChildOutputError:
            raise
        except (OSError, ValueError) as error:
            raise ParserChildOutputError("isolated parser result is missing or invalid") from error
        if not result.ok:
            raise IsolatedParserFailure(
                result.error_code or "isolated_parser_failed",
                result.error_message or "isolated parser failed",
            )
        representations: list[ParsedRepresentation] = []
        total = 0
        for item in result.representations:
            try:
                decoded = base64.b64decode(item.data_base64, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ParserChildOutputError("isolated parser returned invalid base64") from error
            total += len(decoded)
            if total > self._settings.child_output_bytes:
                raise ParserChildOutputError("decoded parser result exceeds output bound")
            representations.append(
                ParsedRepresentation(
                    representation=item.representation,
                    media_type=item.media_type,
                    schema_revision=item.schema_revision,
                    data=decoded,
                )
            )
        return NativeParserOutput(
            representations=tuple(representations),
            warnings=result.warnings,
            hints=result.hints,
        )

    async def _terminate_and_reap(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            await process.wait()
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            async with asyncio.timeout(0.5):
                await process.wait()
                return
        except (LookupError, ProcessLookupError, TimeoutError):
            pass
        if process.returncode is None:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (LookupError, ProcessLookupError):
                pass
        await process.wait()

    async def _cleanup_stale(self, root: Path) -> None:
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self._settings.child_temp_cleanup_age_seconds
        )
        for child in await asyncio.to_thread(lambda: tuple(root.iterdir())):
            if not child.name.startswith("parser-"):
                continue
            try:
                modified = datetime.fromtimestamp(child.lstat().st_mtime, UTC)
            except OSError:
                continue
            if modified > cutoff:
                continue
            await asyncio.to_thread(self._remove_private_workdir, root, child)

    @staticmethod
    def _remove_private_workdir(root: Path, work: Path) -> None:
        resolved_root = root.resolve()
        if work.is_symlink():
            work.unlink(missing_ok=True)
            return
        resolved_work = work.resolve()
        if resolved_work.parent != resolved_root or not resolved_work.name.startswith("parser-"):
            raise ParserIsolationError("refusing to remove an unmanaged parser path")
        shutil.rmtree(resolved_work, ignore_errors=True)
