from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from web_access.bootstrap import lifespan
from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    Environment,
    ObservabilitySettings,
    PrincipalSettings,
    SecuritySettings,
    Settings,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app=AppSettings(environment=Environment.TEST),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="test-agent",
                    tokens=(SecretStr("a" * 32),),
                    scopes=frozenset({"*"}),
                ),
            )
        ),
        content_store=ContentStoreSettings(root=tmp_path),
        observability=ObservabilitySettings(log_format="console"),
    )


@pytest.mark.asyncio
async def test_runtime_lifecycle_order_and_shared_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    original_content_start = lifespan.FilesystemContentStore.start
    original_redis_start = lifespan.RedisDependency.start
    original_redis_close = lifespan.RedisDependency.close

    async def content_start(store: lifespan.FilesystemContentStore) -> None:
        events.append("content:start")
        await original_content_start(store)

    async def redis_start(redis: lifespan.RedisDependency) -> None:
        events.append("redis:start")
        await original_redis_start(redis)

    async def redis_close(redis: lifespan.RedisDependency) -> None:
        events.append("redis:close")
        await original_redis_close(redis)

    async def engine_close(_engine) -> None:
        events.append("database:close")

    def tracing_close(_provider) -> None:
        events.append("tracing:close")

    monkeypatch.setattr(lifespan.FilesystemContentStore, "start", content_start)
    monkeypatch.setattr(lifespan.RedisDependency, "start", redis_start)
    monkeypatch.setattr(lifespan.RedisDependency, "close", redis_close)
    monkeypatch.setattr(lifespan, "close_engine", engine_close)
    monkeypatch.setattr(lifespan, "shutdown_tracing", tracing_close)

    async with lifespan.runtime_lifespan(_settings(tmp_path)) as container:
        assert container.auth is not None
        assert container.health is not None
        assert container.redis is not None
        assert container.content_store is not None
        assert events == ["content:start", "redis:start"]
    assert events == [
        "content:start",
        "redis:start",
        "redis:close",
        "database:close",
        "tracing:close",
    ]


@pytest.mark.asyncio
async def test_multiple_runtime_instances_are_isolated(tmp_path: Path) -> None:
    first_settings = _settings(tmp_path / "first")
    second_settings = _settings(tmp_path / "second")
    async with lifespan.runtime_lifespan(first_settings) as first:
        async with lifespan.runtime_lifespan(second_settings) as second:
            assert first is not second
            assert first.redis is not second.redis
            assert first.database_engine is not second.database_engine
            assert first.metrics is not second.metrics


@pytest.mark.asyncio
async def test_provider_http_clients_are_owned_and_closed_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[RecordingHttpClient] = []

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.name = f"provider-http-{len(created) + 1}"
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True
            close_order.append(self.name)

    close_order: list[str] = []

    def create_client(**_options: object) -> RecordingHttpClient:
        client = RecordingHttpClient()
        created.append(client)
        return client

    monkeypatch.setattr(lifespan.httpx, "AsyncClient", create_client)
    async with lifespan.runtime_lifespan(_settings(tmp_path)):
        assert len(created) == 2
        assert not any(client.closed for client in created)

    assert all(client.closed for client in created)
    assert close_order == ["provider-http-2", "provider-http-1"]


@pytest.mark.asyncio
async def test_failed_startup_releases_created_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []

    async def failing_start(_redis) -> None:
        events.append("redis:start:failed")
        raise RuntimeError("startup failed")

    async def redis_close(_redis) -> None:
        events.append("redis:close")

    async def engine_close(_engine) -> None:
        events.append("database:close")

    monkeypatch.setattr(lifespan.RedisDependency, "start", failing_start)
    monkeypatch.setattr(lifespan.RedisDependency, "close", redis_close)
    monkeypatch.setattr(lifespan, "close_engine", engine_close)
    with pytest.raises(RuntimeError, match="startup failed"):
        async with lifespan.runtime_lifespan(_settings(tmp_path)):
            pytest.fail("failed startup must not yield")
    assert events == ["redis:start:failed", "redis:close", "database:close"]


@pytest.mark.asyncio
async def test_shutdown_timeout_cancels_blocked_closer_and_completes_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_timeout = 0.05
    events: list[str] = []
    closer_started = asyncio.Event()
    closer_cancelled = asyncio.Event()

    class RecordingLogger:
        def info(self, event: str, **_values: object) -> None:
            events.append(event)

        def error(self, event: str, **_values: object) -> None:
            events.append(event)

    async def blocked_close(_redis: lifespan.RedisDependency) -> None:
        closer_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            closer_cancelled.set()
            raise

    monkeypatch.setattr(lifespan.RedisDependency, "close", blocked_close)
    monkeypatch.setattr(lifespan.structlog, "get_logger", lambda _name: RecordingLogger())
    settings = _settings(tmp_path).model_copy(
        update={"security": SecuritySettings(shutdown_timeout_seconds=configured_timeout)}
    )

    async def run_lifespan() -> None:
        async with lifespan.runtime_lifespan(settings):
            pass

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    await asyncio.wait_for(run_lifespan(), timeout=1)
    elapsed = loop.time() - started_at

    assert closer_started.is_set()
    assert closer_cancelled.is_set()
    assert configured_timeout <= elapsed < 0.5
    assert "runtime_shutdown_timed_out" in events
    assert "runtime_stopped" in events
