"""Private controlled Yandex Search v2 protocol endpoint for Compose E2E."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

_RESPONSE = Path("/fixtures/web_search_response.json").read_bytes()
_EXPECTED_KEY = os.environ["MOCK_YANDEX_API_KEY"]
_LOCK = Lock()
_CALLS = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, b'{"status":"ready"}')
            return
        if self.path == "/count":
            with _LOCK:
                payload = json.dumps({"calls": _CALLS}).encode()
            self._send(200, payload)
            return
        self._send(404, b'{"error":"not_found"}')

    def do_POST(self) -> None:
        global _CALLS
        if self.path != "/v2/web/search":
            self._send(404, b'{"error":"not_found"}')
            return
        if self.headers.get("Authorization") != f"Api-Key {_EXPECTED_KEY}":
            self._send(401, b'{"error":"invalid_auth"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 64 * 1024:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            query = payload["query"]
            group = payload["groupSpec"]
            assert payload["folderId"] == "controlled-folder"
            assert payload["responseFormat"] == "FORMAT_XML"
            assert query["searchType"] == "SEARCH_TYPE_RU"
            assert isinstance(query["queryText"], str) and query["queryText"]
            assert isinstance(query["page"], str)
            assert group["groupMode"] == "GROUP_MODE_FLAT"
            assert group["docsInGroup"] == "1"
        except (AssertionError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send(400, b'{"error":"invalid_request"}')
            return
        with _LOCK:
            _CALLS += 1
        self._send(200, _RESPONSE)

    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *arguments: object) -> None:
        _ = format, arguments
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
