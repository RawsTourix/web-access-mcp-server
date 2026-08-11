"""Validate the pinned SearXNG runtime without calling public search engines."""

from __future__ import annotations

import subprocess


def main() -> None:
    probe = """
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=10) as response:
    assert response.status == 200
settings = open("/etc/searxng/settings.yml", encoding="utf-8").read()
assert "formats:" in settings
assert "- json" in settings
print("health-and-static-config-ok")
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
    assert completed.stdout.strip().splitlines()[-1] == "health-and-static-config-ok"
    print("Pinned SearXNG health/static-config smoke passed; public Search calls: 0")


if __name__ == "__main__":
    main()
