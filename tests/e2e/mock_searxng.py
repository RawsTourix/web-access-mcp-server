"""Deterministic local SearXNG-compatible Search API for required E2E."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

_lock = threading.Lock()
_calls = 0
_active = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        global _active, _calls
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if parsed.path == "/state":
            with _lock:
                state = {"calls": _calls, "active": _active}
            self._json(200, state)
            return
        if parsed.path != "/search":
            self._json(404, {"error": "not_found"})
            return

        query = parse_qs(parsed.query).get("q", [""])[0]
        with _lock:
            _calls += 1
            _active += 1
        try:
            if query == "__status_429__":
                self._json(429, {"error": "rate"}, headers={"Retry-After": "1"})
                return
            if query == "__status_500__":
                self._json(503, {"error": "upstream"})
                return
            if query == "__malformed__":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{not-json")
                return
            if query == "__timeout__":
                time.sleep(5)
            if query == "__hold__":
                time.sleep(3)
            page = parse_qs(parsed.query).get("pageno", ["1"])[0]
            self._json(
                200,
                {
                    "query": query,
                    "results": [
                        {
                            "title": f"Controlled result for {query}",
                            "url": f"https://example.test/search/{page}",
                            "content": "Deterministic SearXNG-compatible fixture.",
                            "publishedDate": "2026-08-11T00:00:00Z",
                        }
                    ],
                    "unresponsive_engines": [],
                },
            )
        finally:
            with _lock:
                _active -= 1

    def log_message(self, format: str, *args: object) -> None:
        del format, args
        return

    def _json(self, status: int, payload: object, *, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    # The controlled fixture must be reachable from sibling Compose containers.
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104
