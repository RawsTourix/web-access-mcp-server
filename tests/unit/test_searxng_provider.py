"""S7 fixture and failure tests for the official SearXNG JSON adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory
from web_access.application.common.results import ExecutionStage
from web_access.application.search.models import ProviderSearchRequest
from web_access.application.search.ports import ProviderAttemptError
from web_access.core.config import SearxngSettings
from web_access.core.time import Deadline, FakeClock
from web_access.domain.search import (
    SearchLanguage,
    SearchProviderId,
    SearchSafeMode,
    SearchTimeRange,
)
from web_access.infrastructure.search.searxng import SearxngSearchProvider

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _context(*, deadline: float | None = None) -> ExecutionContext:
    clock = FakeClock(NOW)
    return ExecutionContext(
        operation_id="op-searxng",
        principal=PrincipalContext(principal_id="principal-a", scopes=frozenset({"web:search"})),
        clock=clock,
        cancellation=CancellationToken(),
        deadline=None if deadline is None else Deadline.after(clock, deadline),
    )


def _request(**overrides: object) -> ProviderSearchRequest:
    values: dict[str, object] = {
        "query": "bounded search",
        "provider_id": SearchProviderId.SEARXNG,
        "page": 2,
        "limit": 2,
    }
    values.update(overrides)
    return ProviderSearchRequest.model_validate(values)


def _settings(**overrides: object) -> SearxngSettings:
    values: dict[str, object] = {"endpoint": "https://searxng.internal/root"}
    values.update(overrides)
    return SearxngSettings.model_validate(values)


@pytest.mark.asyncio
async def test_maps_official_query_parameters_and_preserves_result_order() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "sx-request-1"},
            json={
                "results": [
                    {
                        "title": "First",
                        "url": "https://first.example/a",
                        "content": "One",
                        "score": 999,
                        "publishedDate": "2026-08-01T10:00:00Z",
                    },
                    {"title": "Second", "url": "http://second.example/b", "content": "Two"},
                    {"title": "Not requested", "url": "https://third.example"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SearxngSearchProvider(_settings(), client)
        result = await provider.search(
            _context(deadline=3),
            _request(
                language=SearchLanguage.parse("en-US"),
                safe_search=SearchSafeMode.STRICT,
                time_range=SearchTimeRange.MONTH,
            ),
        )

    assert len(calls) == 1
    assert calls[0].url.path == "/root/search"
    assert dict(calls[0].url.params) == {
        "q": "bounded search",
        "format": "json",
        "categories": "general",
        "pageno": "2",
        "language": "en-US",
        "safesearch": "2",
        "time_range": "month",
    }
    assert [item.rank for item in result.results] == [1, 2]
    assert [item.title for item in result.results] == ["First", "Second"]
    assert [item.host for item in result.results] == ["first.example", "second.example"]
    assert result.results[0].published_at == datetime(2026, 8, 1, 10, tzinfo=UTC)
    assert result.provider_request_id == "sx-request-1"
    assert result.retrieved_at == NOW
    assert result.next_page_available is None


@pytest.mark.asyncio
async def test_empty_results_and_partial_engine_failure_are_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={"results": [], "unresponsive_engines": [["engine", "timeout"]]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SearxngSearchProvider(_settings(), client).search(_context(), _request())

    assert result.results == ()
    assert [warning.code for warning in result.warnings] == ["partial_provider_failure"]
    assert result.warnings[0].details == {"engine_failure_count": 1}


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not-json", "searxng_malformed_response"),
        (json.dumps({"answers": []}).encode(), "searxng_malformed_response"),
        (
            json.dumps({"results": [{"title": "Bad", "url": "javascript:alert(1)"}]}).encode(),
            "searxng_malformed_response",
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_responses_are_safe_terminal_errors(payload: bytes, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, content=payload, headers={"x-request-id": "bounded-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await SearxngSearchProvider(_settings(), client).search(_context(), _request())

    assert caught.value.error.code == code
    assert caught.value.error.retryable is False
    assert caught.value.error.details is None
    assert caught.value.stage is ExecutionStage.TERMINAL_KNOWN
    assert caught.value.provider_request_id == "bounded-id"


@pytest.mark.asyncio
async def test_response_body_bound_is_enforced_while_streaming() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, content=b"x" * 1025)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await SearxngSearchProvider(_settings(max_response_bytes=1024), client).search(
                _context(), _request()
            )

    assert caught.value.error.code == "searxng_response_too_large"
    assert caught.value.stage is ExecutionStage.TERMINAL_KNOWN


@pytest.mark.parametrize(
    ("status", "code", "category", "retryable"),
    [
        (429, "searxng_rate_limited", ErrorCategory.RATE_LIMITED, True),
        (503, "searxng_upstream_error", ErrorCategory.UPSTREAM, True),
        (403, "searxng_request_rejected", ErrorCategory.UPSTREAM, False),
    ],
)
@pytest.mark.asyncio
async def test_http_statuses_are_normalized_without_response_body(
    status: int, code: str, category: ErrorCategory, retryable: bool
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        _ = request
        return httpx.Response(
            status,
            content=b"secret upstream diagnostic",
            headers={"retry-after": "7", "x-request-id": "provider-id"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await SearxngSearchProvider(_settings(), client).search(_context(), _request())

    assert calls == 1
    assert caught.value.error.code == code
    assert caught.value.error.category is category
    assert caught.value.error.retryable is retryable
    assert "secret" not in str(caught.value.error.model_dump())
    assert caught.value.stage is ExecutionStage.TERMINAL_KNOWN


@pytest.mark.parametrize(
    ("failure", "stage", "code"),
    [
        (httpx.ConnectError("offline"), ExecutionStage.BEFORE_DISPATCH, "searxng_unavailable"),
        (httpx.ReadTimeout("slow"), ExecutionStage.RESPONSE_LOST, "searxng_timeout"),
    ],
)
@pytest.mark.asyncio
async def test_transport_failure_stage_evidence(
    failure: httpx.HTTPError, stage: ExecutionStage, code: str
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        failure.request = request
        raise failure

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await SearxngSearchProvider(_settings(), client).search(_context(), _request())

    assert calls == 1
    assert caught.value.error.code == code
    assert caught.value.stage is stage


@pytest.mark.asyncio
async def test_expired_deadline_prevents_dispatch() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await SearxngSearchProvider(_settings(), client).search(
                _context(deadline=0), _request()
            )

    assert calls == 0
    assert caught.value.error.code == "search_deadline_exceeded"
    assert caught.value.stage is ExecutionStage.BEFORE_DISPATCH


@pytest.mark.asyncio
async def test_descriptor_declares_exact_searxng_capabilities() -> None:
    async with httpx.AsyncClient() as client:
        descriptor = SearxngSearchProvider(_settings(enabled=False), client).descriptor
    assert descriptor.provider_id is SearchProviderId.SEARXNG
    assert descriptor.enabled is False
    assert descriptor.billable is False
    assert descriptor.capabilities.region is False
    assert descriptor.capabilities.max_results == 50


@pytest.mark.asyncio
async def test_configuration_revision_changes_with_endpoint_and_profile() -> None:
    async with httpx.AsyncClient() as client:
        first = SearxngSearchProvider(_settings(), client).descriptor.configuration_revision
        endpoint_changed = SearxngSearchProvider(
            _settings(endpoint="https://other.internal"), client
        ).descriptor.configuration_revision
        profile_changed = SearxngSearchProvider(
            _settings(profile_revision="profile-revision-v2"), client
        ).descriptor.configuration_revision
    assert len({first, endpoint_changed, profile_changed}) == 3
    assert len(first) == 64
