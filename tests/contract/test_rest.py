from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import SecretStr

from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import ErrorCategory, OperationError
from web_access.application.common.health import Availability
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
)
from web_access.application.search.models import (
    CacheMetadata,
    PaginationMetadata,
    SearchBatchRequest,
    SearchBatchResult,
    SearchQueryData,
)
from web_access.application.search.readiness import (
    PublicProviderCapabilities,
    SearchProviderDiscovery,
    SearchProviderReadinessService,
    SearchProvidersData,
)
from web_access.application.search.service import SearchApplicationService
from web_access.bootstrap.app import create_control_plane
from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    Environment,
    ObservabilitySettings,
    PrincipalSettings,
    Settings,
)
from web_access.domain.search import SearchProviderId, SearchResultItem

TOKEN = "a" * 32
NO_SCOPE_TOKEN = "b" * 32


DependencyName = Literal["postgres", "redis", "content_store"]


def _settings(
    tmp_path: Path,
    mandatory: frozenset[DependencyName] = frozenset(),
    *,
    tracing_enabled: bool = False,
) -> Settings:
    return Settings(
        app=AppSettings(
            environment=Environment.TEST,
            mandatory_dependencies=mandatory,
        ),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="diagnostic-agent",
                    tokens=(SecretStr(TOKEN),),
                    scopes=frozenset(
                        {
                            "admin:read",
                            "search:read",
                            "retrieval:read",
                            "content:read",
                            "content:write",
                        }
                    ),
                ),
                PrincipalSettings(
                    principal_id="limited-agent",
                    tokens=(SecretStr(NO_SCOPE_TOKEN),),
                    scopes=frozenset({"content:read"}),
                ),
            )
        ),
        content_store=ContentStoreSettings(root=tmp_path),
        observability=ObservabilitySettings(tracing_enabled=tracing_enabled),
    )


@pytest.mark.asyncio
async def test_operational_routes_auth_and_safe_status(tmp_path: Path) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            live = await client.get("/health/live")
            assert live.status_code == 200
            assert live.json() == {"status": "alive"}
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready"}

            missing = await client.get("/health/status")
            invalid = await client.get(
                "/health/status", headers={"Authorization": "Bearer invalid-credential"}
            )
            denied = await client.get(
                "/health/status", headers={"Authorization": f"Bearer {NO_SCOPE_TOKEN}"}
            )
            assert missing.status_code == 401
            assert missing.json()["error"]["code"] == "missing_credentials"
            assert invalid.status_code == 401
            assert invalid.json()["error"]["code"] == "invalid_credentials"
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "insufficient_scope"

            status = await client.get(
                "/health/status", headers={"Authorization": f"Bearer {TOKEN}"}
            )
            assert status.status_code == 200
            rendered = status.text
            assert TOKEN not in rendered
            assert "postgresql+asyncpg" not in rendered
            assert str(tmp_path) not in rendered
            metrics = await client.get("/metrics")
            assert metrics.status_code == 200
            assert "web_access_http_requests_total" in metrics.text


@pytest.mark.asyncio
async def test_liveness_survives_mandatory_dependency_outage(tmp_path: Path) -> None:
    app = create_control_plane(
        _settings(tmp_path, frozenset({"postgres", "redis", "content_store"}))
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            ready = await client.get("/health/ready")
            assert ready.status_code == 503
            assert ready.json() == {"status": "unavailable"}


@pytest.mark.asyncio
async def test_unavailable_content_store_is_reported_without_health_500(tmp_path: Path) -> None:
    app = create_control_plane(_settings(tmp_path, frozenset({"content_store"})))
    async with app.router.lifespan_context(app):
        staging = tmp_path / "staging"
        shutil.rmtree(staging)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            status = await client.get(
                "/health/status", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert live.status_code == 200
        assert ready.status_code == 503
        assert status.status_code == 200
        content_store = next(
            dependency
            for dependency in status.json()["service"]["dependencies"]
            if dependency["name"] == "content_store"
        )
        assert content_store["status"] == "unavailable"
        assert content_store["code"] == "probe_failed"
        assert not staging.exists()


@pytest.mark.asyncio
async def test_correlation_headers_are_bounded_and_server_owned(tmp_path: Path) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            accepted = await client.get("/health/live", headers={"X-Request-ID": "caller-123"})
            assert accepted.headers["X-Request-ID"] == "caller-123"
            assert accepted.headers["X-Operation-ID"].startswith("op_")
            rejected = await client.get("/health/live", headers={"X-Request-ID": "bad value"})
            assert rejected.headers["X-Request-ID"].startswith("req_")


def test_openapi_has_exact_v03_routes_and_bearer_security(tmp_path: Path) -> None:
    schema = create_control_plane(_settings(tmp_path)).openapi()
    assert schema["info"]["version"] == "0.3.0"
    assert set(schema["paths"]) == {
        "/health/live",
        "/health/ready",
        "/health/status",
        "/metrics",
        "/api/v1/search",
        "/api/v1/search/providers",
        "/api/v1/retrieval/fetch",
        "/api/v1/content/{content_id}",
        "/api/v1/content/{content_id}/data",
        "/api/v1/content/{content_id}/representations",
        "/api/v1/content/inspect",
        "/api/v1/content/native-parse",
    }
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    status_operation = schema["paths"]["/health/status"]["get"]
    assert status_operation["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/api/v1/search"]["post"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/api/v1/search/providers"]["get"]["security"] == [{"BearerAuth": []}]
    for path, method in (
        ("/api/v1/retrieval/fetch", "post"),
        ("/api/v1/content/{content_id}", "get"),
        ("/api/v1/content/{content_id}/data", "get"),
        ("/api/v1/content/{content_id}/representations", "get"),
        ("/api/v1/content/inspect", "post"),
        ("/api/v1/content/native-parse", "post"),
    ):
        assert schema["paths"][path][method]["security"] == [{"BearerAuth": []}]
    rendered = str(schema).lower()
    for forbidden in ("browser", "jobs", "upload", "sqlalchemy", "redis_url"):
        assert f'"/{forbidden}' not in rendered
    components = schema["components"]["schemas"]
    fetch = components["RestFetchRequest"]
    assert fetch["properties"]["items"]["minItems"] == 1
    assert fetch["properties"]["items"]["maxItems"] == 32
    assert fetch["properties"]["processing_level"]["default"] == "native"
    assert components["RetrievalProcessingLevel"]["enum"] == [
        "store_only",
        "inspect",
        "native",
    ]
    assert components["RestFetchItem"]["properties"]["url"]["maxLength"] == 8192
    ids = components["RestContentIdsRequest"]["properties"]["content_ids"]
    assert ids["minItems"] == 1 and ids["maxItems"] == 32
    assert ids["uniqueItems"] is True
    assert ids["items"]["maxLength"] == 128
    native = components["RestNativeParseRequest"]
    assert native["properties"]["reuse_existing"]["default"] is True
    assert set(native["properties"]) == {"content_ids", "reuse_existing"}


class _FakeSearch:
    def __init__(self) -> None:
        self.context: ExecutionContext | None = None
        self.request: SearchBatchRequest | None = None

    async def search(
        self, context: ExecutionContext, request: SearchBatchRequest
    ) -> OperationResult[SearchBatchResult]:
        self.context = context
        self.request = request
        now = datetime(2026, 8, 11, tzinfo=UTC)
        succeeded = BatchItemResult[SearchQueryData](
            index=0,
            outcome=LeafOutcome.SUCCEEDED,
            data=SearchQueryData(
                query=request.queries[0].query,
                provider_id=SearchProviderId.SEARXNG,
                page=request.queries[0].page,
                requested_limit=request.queries[0].limit,
                results=(
                    SearchResultItem(
                        rank=1,
                        title="Result",
                        url="https://example.test/result",
                    ),
                ),
                cache=CacheMetadata(cached=False, retrieved_at=now),
                pagination=PaginationMetadata(page=request.queries[0].page),
            ),
        )
        rejected = BatchItemResult[SearchQueryData](
            index=1,
            outcome=LeafOutcome.REJECTED,
            error=OperationError(
                category=ErrorCategory.UNSUPPORTED,
                code="unsupported_option",
                message="The selected provider does not support this option.",
            ),
        )
        return OperationResult[SearchBatchResult](
            operation_id=context.operation_id,
            outcome=OperationOutcome.PARTIAL_SUCCESS,
            data=SearchBatchResult(items=(succeeded, rejected)),
        )


class _FakeReadiness:
    async def discover(self, context: ExecutionContext) -> OperationResult[SearchProvidersData]:
        providers = (
            SearchProviderDiscovery(
                provider_id=SearchProviderId.SEARXNG,
                name="SearXNG",
                enabled=True,
                billable=False,
                capabilities=PublicProviderCapabilities(
                    pagination=True,
                    language=True,
                    region=True,
                    safe_search=True,
                    time_range=True,
                ),
                readiness=Availability.READY,
            ),
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.SUCCEEDED,
            data=SearchProvidersData(providers=providers),
        )


class _ProviderAuthRejectedSearch:
    async def search(
        self, context: ExecutionContext, request: SearchBatchRequest
    ) -> OperationResult[SearchBatchResult]:
        _ = request
        error = OperationError(
            category=ErrorCategory.UPSTREAM,
            code="provider_auth_rejected",
            message="Yandex Search отклонил серверные credentials.",
        )
        return OperationResult(
            operation_id=context.operation_id,
            outcome=OperationOutcome.FAILED,
            data=SearchBatchResult(
                items=(BatchItemResult(index=0, outcome=LeafOutcome.FAILED, error=error),)
            ),
            error=error,
        )


@pytest.mark.asyncio
async def test_search_routes_are_exact_scoped_and_project_canonical_results(
    tmp_path: Path,
) -> None:
    fake_search = _FakeSearch()
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        app.state.container = replace(
            app.state.container,
            search=cast(SearchApplicationService, fake_search),
            search_readiness=cast(SearchProviderReadinessService, _FakeReadiness()),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            missing = await client.post("/api/v1/search", json={"queries": [{"query": "x"}]})
            denied = await client.get(
                "/api/v1/search/providers",
                headers={"Authorization": f"Bearer {NO_SCOPE_TOKEN}"},
            )
            response = await client.post(
                "/api/v1/search",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "queries": [
                        {"query": "  first query  "},
                        {
                            "query": "second query",
                            "provider": "yandex",
                            "language": "EN-us",
                            "region": "ru-moscow",
                            "safe_search": "strict",
                            "time_range": "month",
                        },
                    ]
                },
            )
            providers = await client.get(
                "/api/v1/search/providers",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    assert missing.status_code == 401
    assert denied.status_code == 403
    assert response.status_code == 200
    body = response.json()
    assert body["operation_id"] == response.headers["X-Operation-ID"]
    assert body["outcome"] == "partial"
    assert [item["index"] for item in body["data"]["items"]] == [0, 1]
    assert body["data"]["items"][0]["data"]["query"] == "first query"
    assert fake_search.context is not None
    assert fake_search.context.principal.principal_id == "diagnostic-agent"
    assert fake_search.context.operation_id == body["operation_id"]
    assert fake_search.request is not None
    assert str(fake_search.request.queries[1].language) == "en-US"

    assert providers.status_code == 200
    providers_body = providers.json()
    assert providers_body["operation_id"] == providers.headers["X-Operation-ID"]
    assert providers_body["outcome"] == "succeeded"
    provider = providers_body["data"]["providers"][0]
    assert set(provider) == {
        "provider_id",
        "name",
        "enabled",
        "billable",
        "capabilities",
        "readiness",
    }
    assert set(provider["capabilities"]) == {
        "pagination",
        "language",
        "region",
        "safe_search",
        "time_range",
    }
    assert provider["readiness"] == "ready"


@pytest.mark.asyncio
async def test_authenticated_client_never_receives_401_for_yandex_credentials(
    tmp_path: Path,
) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        app.state.container = replace(
            app.state.container,
            search=cast(SearchApplicationService, _ProviderAuthRejectedSearch()),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/search",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"queries": [{"query": "valid", "provider": "yandex"}]},
            )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "category": "upstream",
        "code": "provider_auth_rejected",
        "message": "Yandex Search отклонил серверные credentials.",
        "retryable": False,
        "retry_after_seconds": None,
        "fields": [],
        "details": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        {"query": "x", "unknown": True},
        {"query": "x", "provider": "unknown"},
        {"query": "x", "language": None},
        {"query": "x", "language": "not_a_language"},
        {"query": "x", "region": "RU"},
        {"query": "x", "limit": 51},
        {"query": "x" * 4097},
    ],
)
async def test_search_rest_rejects_non_contract_inputs(
    tmp_path: Path, query: dict[str, object]
) -> None:
    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/search",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"queries": [query]},
            )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("category", "outcome", "expected_status"),
    [
        (ErrorCategory.RATE_LIMITED, OperationOutcome.FAILED, 429),
        (ErrorCategory.CAPACITY, OperationOutcome.FAILED, 503),
        (ErrorCategory.INFRASTRUCTURE, OperationOutcome.FAILED, 503),
        (ErrorCategory.UPSTREAM, OperationOutcome.FAILED, 502),
        (ErrorCategory.TIMEOUT, OperationOutcome.FAILED, 504),
        (ErrorCategory.VALIDATION, OperationOutcome.REJECTED, 422),
        (ErrorCategory.PERMISSION, OperationOutcome.REJECTED, 403),
        (ErrorCategory.UNKNOWN_OUTCOME, OperationOutcome.UNKNOWN, 502),
    ],
)
async def test_fully_unsuccessful_search_uses_canonical_http_status(
    tmp_path: Path,
    category: ErrorCategory,
    outcome: OperationOutcome,
    expected_status: int,
) -> None:
    class FailedSearch:
        async def search(
            self, context: ExecutionContext, request: SearchBatchRequest
        ) -> OperationResult[SearchBatchResult]:
            _ = request
            leaf = (
                LeafOutcome.UNKNOWN
                if outcome is OperationOutcome.UNKNOWN
                else LeafOutcome.REJECTED
                if outcome is OperationOutcome.REJECTED
                else LeafOutcome.FAILED
            )
            error = OperationError(
                category=category,
                code="controlled_failure",
                message="Контролируемая ошибка поиска.",
            )
            return OperationResult(
                operation_id=context.operation_id,
                outcome=outcome,
                data=SearchBatchResult(
                    items=(BatchItemResult(index=0, outcome=leaf, error=error),)
                ),
                error=error,
            )

    app = create_control_plane(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        app.state.container = replace(
            app.state.container,
            search=cast(SearchApplicationService, FailedSearch()),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/search",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"queries": [{"query": "x"}]},
            )

    assert response.status_code == expected_status
    assert response.json()["error"]["category"] == category.value


@pytest.mark.asyncio
async def test_internal_error_is_safe_and_structurally_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canary = "internal-exception-bearer-canary-secret"
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    monkeypatch.setattr(
        "web_access.bootstrap.app.configure_tracing",
        lambda _settings, _service_name: provider,
    )
    app = create_control_plane(_settings(tmp_path, tracing_enabled=True))
    trace_id = "fedcba0987654321fedcba0987654321"

    async def fail() -> None:
        raise RuntimeError(canary)

    app.add_api_route("/_test/fail", fail, methods=["GET"], include_in_schema=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/_test/fail",
                headers={
                    "X-Request-ID": "req-canary",
                    "traceparent": f"00-{trace_id}-1234567890abcdef-01",
                },
            )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert canary not in response.text
    events = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    error_event = next(event for event in events if event.get("event") == "rest_internal_error")
    assert error_event["operation_id"].startswith("op_")
    assert error_event["request_id"] == "req-canary"
    assert error_event["trace_id"] == trace_id
    assert canary not in json.dumps(error_event)


@pytest.mark.asyncio
async def test_fastapi_request_span_uses_local_provider_and_w3c_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "web_access.bootstrap.app.configure_tracing",
        lambda _settings, _service_name: provider,
    )
    app = create_control_plane(_settings(tmp_path, tracing_enabled=True))
    trace_id = int("1234567890abcdef1234567890abcdef", 16)
    parent_span_id = "1234567890abcdef"
    traceparent = f"00-{trace_id:032x}-{parent_span_id}-01"
    canary = "request-body-bearer-canary-secret"

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.request(
                "GET",
                "/health/live",
                headers={
                    "traceparent": traceparent,
                    "authorization": f"Bearer {canary}",
                },
                content=canary.encode(),
            )
        spans = exporter.get_finished_spans()
        server_spans = [span for span in spans if span.kind is SpanKind.SERVER]
        assert response.status_code == 200
        assert server_spans
        assert any(
            span.context is not None and span.context.trace_id == trace_id for span in server_spans
        )
        assert canary not in repr([span.attributes for span in spans])
