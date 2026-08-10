"""Validate the real pinned SearXNG container's private JSON protocol."""

from __future__ import annotations

import json
import subprocess


def main() -> None:
    probe = """
import json
import urllib.parse
import urllib.request

params = urllib.parse.urlencode({
    "q": "1+1",
    "format": "json",
    "categories": "general",
    "pageno": "1",
    "safesearch": "2",
    "time_range": "day",
})
request = urllib.request.Request(
    "http://127.0.0.1:8080/search?" + params,
    headers={"X-Forwarded-For": "127.0.0.1"},
)
with urllib.request.urlopen(request, timeout=20) as response:
    body = response.read(2 * 1024 * 1024 + 1)
    assert response.status == 200
    assert response.headers.get_content_type() == "application/json"
    assert len(body) <= 2 * 1024 * 1024
payload = json.loads(body)
assert isinstance(payload, dict)
assert isinstance(payload.get("results"), list)
print(json.dumps({"result_count": len(payload["results"])}))
"""
    # The executable and every argument are repository-owned constants.
    completed = subprocess.run(  # noqa: S603
        # Docker is an explicit prerequisite of this Compose-only E2E test.
        ["docker", "compose", "exec", "-T", "searxng", "python", "-c", probe],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    evidence = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(evidence["result_count"], int)
    print("Pinned SearXNG JSON protocol smoke passed", evidence)


if __name__ == "__main__":
    main()
