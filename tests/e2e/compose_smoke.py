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
        providers = await rest.get(
            "/api/v1/search/providers", headers={"Authorization": f"Bearer {token}"}
        )
        mixed_queries = [
            {
                "query": "1+1",
                "provider": "default",
                "language": "en-US",
                "safe_search": "strict",
                "time_range": "day",
                "page": 1,
                "limit": 2,
            },
            {
                "query": "Python programming language",
                "provider": "searxng",
                "page": 2,
                "limit": 1,
            },
            {
                "query": "disabled paid provider",
                "provider": "yandex",
                "region": "ru",
                "safe_search": "moderate",
                "time_range": "month",
            },
        ]
        search = await rest.post(
            "/api/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"queries": mixed_queries},
        )
        cached = await rest.post(
            "/api/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"queries": [mixed_queries[0]]},
        )

    assert live.status_code == 200 and live.json() == {"status": "alive"}
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert unauthorized.status_code == 401
    assert status.status_code == 200 and status.json()["service"]["status"] == "ready"
    assert token not in status.text
    assert metrics.status_code == 200
    assert "web_access_http_requests_total" in metrics.text
    assert providers.status_code == 200
    discovered = {item["provider_id"]: item for item in providers.json()}
    assert discovered["searxng"]["readiness"] == "ready"
    assert discovered["yandex"]["enabled"] is False
    assert discovered["yandex"]["readiness"] == "unavailable"
    assert search.status_code == 200
    search_body = search.json()
    assert search_body["operation_id"] == search.headers["X-Operation-ID"]
    assert search_body["outcome"] == "partial"
    items = search_body["data"]["items"]
    assert [item["index"] for item in items] == [0, 1, 2]
    assert [item["outcome"] for item in items] == ["succeeded", "succeeded", "rejected"]
    assert items[2]["error"]["code"] == "provider_disabled"
    assert cached.status_code == 200
    cached_data = cached.json()["data"]["items"][0]["data"]
    first_data = items[0]["data"]
    assert cached_data["cache"]["cached"] is True
    assert cached_data["cache"]["retrieved_at"] == first_data["cache"]["retrieved_at"]
    assert cached_data["usage"] == {
        "upstream_attempts": 0,
        "rate_units": 0,
        "billable_attempts": 0,
        "internal_retries": 0,
    }

    async with Client(f"{base_url}/mcp/", auth=token) as mcp:
        tools = await mcp.list_tools()
        assert [tool.name for tool in tools] == ["web_search"]
        result = await mcp.call_tool("web_search", {"queries": ["Web Access MCP"], "limit": 2})
        assert result.structured_content is not None
        assert result.structured_content["outcome"] == "succeeded"

    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "web_access",
        "-d",
        "web_access",
        "-Atc",
        "SELECT count(*) FROM search_provider_attempts WHERE provider_id='yandex'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace"))
    assert stdout.decode().strip() == "0"

    print("Compose REST/MCP Search smoke passed; live Yandex calls: 0")


if __name__ == "__main__":
    asyncio.run(main())
