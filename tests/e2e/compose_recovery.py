"""Bounded fault/recovery and graceful-shutdown evidence for the Compose stack."""

from __future__ import annotations

import asyncio
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
    # The HTTP timeout must exceed the configured DB pool probe timeout so the
    # smoke observes the normalized 503 instead of abandoning the probe early.
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:

        async def ready(expected: int) -> bool:
            try:
                return (await client.get("/health/ready")).status_code == expected
            except httpx.HTTPError:
                return False

        await _poll(lambda: ready(200), description="initial API readiness")
        api_container = await _compose("ps", "-q", "api")
        if not api_container:
            raise RuntimeError("Compose API container is not running")

        try:
            await _compose("stop", "postgres")
            await _poll(lambda: ready(503), description="PostgreSQL outage detection")
            await _compose("start", "postgres")
            await _poll(lambda: ready(200), description="PostgreSQL connection recovery")
            await _compose(
                "exec", "-T", "postgres", "pg_isready", "-U", "web_access", "-d", "web_access"
            )
            assert await _compose("ps", "-q", "api") == api_container

            for attempt in range(2):
                await _compose("stop", "redis")
                await _poll(
                    lambda: ready(503),
                    description=f"Redis outage detection {attempt + 1}",
                )
                await _compose("start", "redis")
                await _poll(
                    lambda: ready(200),
                    description=f"Redis connection recovery {attempt + 1}",
                )
                assert "PONG" in await _compose("exec", "-T", "redis", "redis-cli", "ping")
                assert await _compose("ps", "-q", "api") == api_container

            await _compose("stop", "api", deadline_seconds=30)
            logs = await _compose("logs", "--no-color", "api")
            assert "runtime_stopped" in logs
            await _compose("start", "api")
            await _poll(lambda: ready(200), description="API restart after graceful shutdown")
        finally:
            await _compose("start", "postgres", "redis", "api")
            await _poll(lambda: ready(200), description="final recovered stack")

    print("Compose PostgreSQL/Redis recovery and graceful shutdown passed")


if __name__ == "__main__":
    asyncio.run(main())
