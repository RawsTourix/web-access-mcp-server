"""Network-level smoke test for the Docker Compose control plane."""

from __future__ import annotations

import asyncio
import os

import httpx
from fastmcp import Client


async def main() -> None:
    base_url = os.getenv("WEB_ACCESS_SMOKE_BASE_URL", "http://127.0.0.1:8000")
    token = os.environ["WEB_ACCESS_SMOKE_TOKEN"]

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as rest:
        live = await rest.get("/health/live")
        ready = await rest.get("/health/ready")
        unauthorized = await rest.get("/health/status")
        status = await rest.get("/health/status", headers={"Authorization": f"Bearer {token}"})
        metrics = await rest.get("/metrics")

    assert live.status_code == 200 and live.json() == {"status": "alive"}
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert unauthorized.status_code == 401
    assert status.status_code == 200 and status.json()["service"]["status"] == "ready"
    assert token not in status.text
    assert metrics.status_code == 200
    assert "web_access_http_requests_total" in metrics.text

    async with Client(f"{base_url}/mcp/", auth=token) as mcp:
        assert await mcp.list_tools() == []

    print("Compose REST/MCP smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
