"""Bounded fault/recovery and graceful-shutdown evidence for the Compose stack."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from time import monotonic

import httpx


async def _compose(*arguments: str, deadline_seconds: float = 90) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), deadline_seconds)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(arguments)} failed: {stderr.decode(errors='replace')}"
        )
    return stdout.decode().strip()


async def _poll(
    condition: Callable[[], Awaitable[bool]], *, description: str, deadline_seconds: float = 45
) -> None:
    deadline = monotonic() + deadline_seconds
    while monotonic() < deadline:
        if await condition():
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"deadline exceeded while waiting for {description}")


async def main() -> None:
    base_url = os.getenv("WEB_ACCESS_SMOKE_BASE_URL", "http://127.0.0.1:8000")
    yandex_test_url = os.getenv("WEB_ACCESS_YANDEX_TEST_BASE_URL", "http://127.0.0.1:18084")
    token = os.environ["WEB_ACCESS_SMOKE_TOKEN"]
    authorization = {"Authorization": f"Bearer {token}"}
    # The HTTP timeout must exceed the configured DB pool probe timeout so the
    # smoke observes the normalized 503 instead of abandoning the probe early.
    async with httpx.AsyncClient(base_url=base_url, timeout=35) as client:

        async def ready(expected: int) -> bool:
            try:
                # Docker Desktop can retain a stale host-port connection across container
                # stop/start; readiness must probe the current listener with a fresh pool.
                async with httpx.AsyncClient(base_url=base_url, timeout=35) as probe:
                    return (await probe.get("/health/ready")).status_code == expected
            except httpx.HTTPError:
                return False

        async def search(query: str) -> httpx.Response:
            return await client.post(
                "/api/v1/search",
                headers=authorization,
                json={"queries": [{"query": query, "limit": 1}]},
            )

        async def search_succeeds(query: str) -> bool:
            try:
                response = await search(query)
                return response.status_code == 200 and response.json()["outcome"] == "succeeded"
            except (httpx.HTTPError, KeyError, ValueError):
                return False

        async def provider_readiness(provider_id: str, expected: str) -> bool:
            try:
                response = await client.get("/api/v1/search/providers", headers=authorization)
                providers = {
                    item["provider_id"]: item for item in response.json()["data"]["providers"]
                }
                return providers[provider_id]["readiness"] == expected
            except (httpx.HTTPError, KeyError, ValueError):
                return False

        async def mock_yandex_calls() -> int:
            output = await _compose(
                "exec",
                "-T",
                "mock-yandex",
                "python",
                "-c",
                "import urllib.request; print(urllib.request.urlopen("
                "'http://127.0.0.1:8080/count').read().decode())",
            )
            return int(json.loads(output.splitlines()[-1])["calls"])

        await _poll(lambda: ready(200), description="initial API readiness")
        api_container = await _compose("ps", "-q", "api")
        if not api_container:
            raise RuntimeError("Compose API container is not running")

        try:
            initial_mock_calls = await mock_yandex_calls()
            controlled_payload = {
                "queries": [
                    {
                        "query": f"controlled paid success {initial_mock_calls}",
                        "provider": "yandex",
                        "region": "ru",
                        "safe_search": "strict",
                        "time_range": "month",
                        "limit": 2,
                    }
                ]
            }
            controlled: httpx.Response | None = None
            deadline = monotonic() + 15
            while monotonic() < deadline:
                candidate = await client.post(
                    f"{yandex_test_url}/api/v1/search",
                    headers=authorization,
                    json=controlled_payload,
                )
                if candidate.status_code == 200 and candidate.json()["outcome"] == "succeeded":
                    controlled = candidate
                    break
                await asyncio.sleep(0.25)
            if controlled is None:
                raise TimeoutError("controlled Yandex profile did not recover admission")
            assert controlled.status_code == 200
            assert controlled.json()["outcome"] == "succeeded"
            controlled_data = controlled.json()["data"]["items"][0]["data"]
            assert controlled_data["provider_id"] == "yandex"
            assert controlled_data["usage"]["billable_attempts"] == 1
            assert await mock_yandex_calls() == initial_mock_calls + 1

            await _compose("stop", "postgres")
            await _poll(lambda: ready(503), description="PostgreSQL outage detection")
            free_search = await search("SearXNG survives PostgreSQL outage")
            assert free_search.status_code == 200
            assert free_search.json()["outcome"] == "succeeded"
            calls_before_failed_paid = await mock_yandex_calls()
            failed_paid = await client.post(
                f"{yandex_test_url}/api/v1/search",
                headers=authorization,
                json={
                    "queries": [
                        {
                            "query": "must fail closed while PostgreSQL is down",
                            "provider": "yandex",
                        }
                    ]
                },
            )
            assert failed_paid.status_code == 503
            assert failed_paid.json()["outcome"] == "failed"
            assert (
                failed_paid.json()["data"]["items"][0]["error"]["code"]
                == "usage_accounting_unavailable"
            )
            assert await mock_yandex_calls() == calls_before_failed_paid
            await _compose("start", "postgres")
            await _poll(lambda: ready(200), description="PostgreSQL connection recovery")
            await _compose(
                "exec", "-T", "postgres", "pg_isready", "-U", "web_access", "-d", "web_access"
            )
            paid_rows = await _compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "web_access",
                "-d",
                "web_access",
                "-Atc",
                "SELECT count(*) FROM search_provider_attempts "
                "WHERE provider_id='yandex' AND stage='completed'",
            )
            assert int(paid_rows.splitlines()[-1]) >= 1
            assert await _compose("ps", "-q", "api") == api_container

            for attempt in range(2):
                await _compose("stop", "redis")
                await _poll(
                    lambda: ready(503),
                    description=f"Redis outage detection {attempt + 1}",
                )
                rejected = await search(f"Redis fail closed {attempt}")
                assert rejected.status_code == 503
                assert rejected.json()["outcome"] == "failed"
                assert (
                    rejected.json()["data"]["items"][0]["error"]["code"]
                    == "search_admission_unavailable"
                )
                await _compose("start", "redis")
                await _poll(
                    lambda: ready(200),
                    description=f"Redis connection recovery {attempt + 1}",
                )
                assert "PONG" in await _compose("exec", "-T", "redis", "redis-cli", "ping")
                assert await provider_readiness("searxng", "unavailable")
                if attempt == 1:
                    await _compose("restart", "api", deadline_seconds=30)
                    await _poll(
                        lambda: ready(200), description="new API replica after Redis restart"
                    )
                    new_replica = await search("new replica after Redis restart")
                    assert new_replica.status_code == 503
                    assert (
                        new_replica.json()["data"]["items"][0]["error"]["code"]
                        == "search_admission_unavailable"
                    )
                assert await _compose("ps", "-q", "api") == api_container
                recovery_query = f"Redis recovery Search {attempt}"
                await _poll(
                    lambda recovery_query=recovery_query: search_succeeds(recovery_query),
                    description=f"Search limiter recovery {attempt + 1}",
                    deadline_seconds=25,
                )
                assert await provider_readiness("searxng", "ready")
                cached = await search(recovery_query)
                assert cached.json()["data"]["items"][0]["data"]["cache"]["cached"] is True

            await _compose("exec", "-T", "redis", "redis-cli", "FLUSHDB")
            flush_rejected = await search("Redis flush must fail closed")
            assert flush_rejected.status_code == 503
            assert (
                flush_rejected.json()["data"]["items"][0]["error"]["code"]
                == "search_admission_unavailable"
            )
            assert await provider_readiness("searxng", "unavailable")
            await _poll(
                lambda: search_succeeds("Redis FLUSHDB recovery without API restart"),
                description="Redis FLUSHDB conservative-horizon recovery",
                deadline_seconds=25,
            )
            assert await provider_readiness("searxng", "ready")
            assert await _compose("ps", "-q", "api") == api_container

            await _compose("stop", "mock-searxng")
            outage = await search("SearXNG outage must not fall back")
            assert outage.status_code == 502
            assert outage.json()["outcome"] == "failed"
            assert outage.json()["data"]["items"][0]["error"]["code"] in {
                "searxng_timeout",
                "searxng_unavailable",
                "searxng_transport_error",
            }
            providers = await client.get("/api/v1/search/providers", headers=authorization)
            discovered = {
                item["provider_id"]: item for item in providers.json()["data"]["providers"]
            }
            assert discovered["searxng"]["readiness"] == "unavailable"
            assert discovered["yandex"]["enabled"] is False
            await _compose("start", "mock-searxng")
            await _poll(
                lambda: search_succeeds("SearXNG recovered without API restart"),
                description="SearXNG Search recovery",
                deadline_seconds=45,
            )
            assert await _compose("ps", "-q", "api") == api_container

            await _compose("stop", "api", deadline_seconds=30)
            logs = await _compose("logs", "--no-color", "api")
            assert "runtime_stopped" in logs
            await _compose("start", "api")
            await _poll(lambda: ready(200), description="API restart after graceful shutdown")
        finally:
            await _compose(
                "start",
                "postgres",
                "redis",
                "searxng",
                "mock-searxng",
                "mock-yandex",
                "api",
                "api-yandex-test",
            )
            await _poll(lambda: ready(200), description="final recovered stack")

    print("Compose PostgreSQL/Redis recovery and graceful shutdown passed")


if __name__ == "__main__":
    asyncio.run(main())
