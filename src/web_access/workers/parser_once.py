"""Execute exactly one allowlisted parser request and exit."""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

from web_access.application.content.isolation import (
    IsolatedParserRequest,
    IsolatedParserResult,
    IsolatedRepresentation,
)
from web_access.domain.content import ContentRepresentationKind

Handler = Callable[[bytes, dict[str, object]], IsolatedParserResult]


class WorkerRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def main() -> int:
    if len(sys.argv) != 3:
        return 64
    request_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    if (
        request_path.parent != result_path.parent
        or request_path.name != "request.json"
        or result_path.name != "result.json"
    ):
        return 64
    output_limit = 64 * 1024
    try:
        raw_request = request_path.read_bytes()
        if len(raw_request) > 64 * 1024:
            raise WorkerRequestError("invalid_parser_request", "parser request is oversized")
        request = IsolatedParserRequest.model_validate_json(raw_request)
        output_limit = request.max_output_bytes
        _apply_resource_limits(request)
        input_path = request_path.parent / request.input_file
        if input_path.resolve().parent != request_path.parent or input_path.is_symlink():
            raise WorkerRequestError("invalid_parser_input", "parser input path is invalid")
        if input_path.stat().st_size > request.max_input_bytes:
            raise WorkerRequestError("parser_input_limit", "parser input exceeds its bound")
        data = input_path.read_bytes()
        handler = _handler(request.parser_id)
        result = handler(data, dict(request.parameters))
    except WorkerRequestError as error:
        result = IsolatedParserResult(
            ok=False,
            error_code=error.code,
            error_message=str(error),
        )
    except Exception:
        result = IsolatedParserResult(
            ok=False,
            error_code="parser_child_internal",
            error_message="isolated parser failed internally",
        )
    payload = result.model_dump_json().encode()
    if len(payload) > output_limit:
        return 74
    temporary = result_path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, result_path)
    return 0


def _handler(parser_id: str) -> Handler:
    if parser_id == "pdf":
        from web_access.workers.pdf_parser import parse_pdf

        return parse_pdf
    if os.environ.get("WEB_ACCESS_PARSER_TEST_MODE") == "1":
        test_handlers: dict[str, Handler] = {
            "test_crash": _crash,
            "test_echo": _echo,
            "test_environment": _environment,
            "test_network_probe": _network_probe,
            "test_sleep": _sleep,
        }
        if parser_id in test_handlers:
            return test_handlers[parser_id]
    raise WorkerRequestError("parser_not_allowed", "parser ID is not allowlisted by child")


def _echo(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    del parameters
    return IsolatedParserResult(
        ok=True,
        representations=(
            IsolatedRepresentation(
                representation=ContentRepresentationKind.BINARY,
                media_type="application/octet-stream",
                schema_revision="test-echo-v1",
                data_base64=base64.b64encode(data).decode("ascii"),
            ),
        ),
    )


def _sleep(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    del data
    seconds = parameters.get("seconds", 1)
    if not isinstance(seconds, int | float) or not 0 <= seconds <= 60:
        raise WorkerRequestError("invalid_test_parameter", "invalid sleep duration")
    time.sleep(float(seconds))
    return _echo(b"slept", {})


def _crash(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    del data, parameters
    os._exit(23)


def _network_probe(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    del data
    host = parameters.get("host")
    port = parameters.get("port")
    if not isinstance(host, str) or not isinstance(port, int):
        raise WorkerRequestError("invalid_test_parameter", "invalid network probe target")
    try:
        with socket.create_connection((host, port), timeout=1):
            blocked = False
    except OSError:
        blocked = True
    if not blocked:
        raise WorkerRequestError("network_isolation_failed", "parser child reached the network")
    return _echo(json.dumps({"blocked": True}).encode(), {})


def _environment(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    del data, parameters
    sensitive = (
        "WEB_ACCESS_DATABASE__URL",
        "WEB_ACCESS_REDIS__URL",
        "WEB_ACCESS_AUTH__PRINCIPALS",
        "WEB_ACCESS_SEARCH__YANDEX__API_KEY",
        "WEB_ACCESS_CONTENT_STORE__ROOT",
    )
    observed = {key: key in os.environ for key in sensitive}
    return _echo(json.dumps(observed, sort_keys=True).encode(), {})


def _apply_resource_limits(request: IsolatedParserRequest) -> None:
    if os.name == "nt":
        return
    import resource

    limits = (
        (resource.RLIMIT_CPU, request.cpu_seconds),
        (resource.RLIMIT_AS, request.memory_bytes),
        (resource.RLIMIT_FSIZE, request.max_output_bytes),
        (resource.RLIMIT_NOFILE, request.open_files),
        (resource.RLIMIT_NPROC, request.processes),
    )
    for resource_id, value in limits:
        resource.setrlimit(resource_id, (value, value))


if __name__ == "__main__":
    raise SystemExit(main())
