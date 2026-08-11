"""S10 official Yandex Search API v2 fixture and cost-safety tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import ErrorCategory
from web_access.application.common.results import ExecutionStage
from web_access.application.search.language import normalize_search_language
from web_access.application.search.models import ProviderSearchRequest, SearchQuery
from web_access.application.search.ports import ProviderAttemptError
from web_access.application.search.registry import ProviderResolutionError, SearchProviderRegistry
from web_access.core.config import YandexSearchSettings
from web_access.core.time import Deadline, FakeClock
from web_access.domain.search import (
    SearchProviderId,
    SearchSafeMode,
    SearchTimeRange,
)
from web_access.infrastructure.search.yandex import YandexSearchProvider

NOW = datetime(2026, 8, 11, tzinfo=UTC)
FIXTURES = Path("tests/fixtures/yandex")


def _context(*, deadline: float | None = None) -> ExecutionContext:
    clock = FakeClock(NOW)
    return ExecutionContext(
        operation_id="op-yandex",
        principal=PrincipalContext(principal_id="principal-a", scopes=frozenset({"search:read"})),
        clock=clock,
        cancellation=CancellationToken(),
        deadline=None if deadline is None else Deadline.after(clock, deadline),
    )


def _settings(**overrides: object) -> YandexSearchSettings:
    values: dict[str, object] = {
        "enabled": True,
        "folder_id": "fixture-folder-id",
        "api_key": "fixture-api-key-secret",
    }
    values.update(overrides)
    return YandexSearchSettings.model_validate(values)


def _request(**overrides: object) -> ProviderSearchRequest:
    values: dict[str, object] = {
        "query": "официальный контракт",
        "provider_id": SearchProviderId.YANDEX,
        "page": 1,
        "limit": 2,
    }
    values.update(overrides)
    return ProviderSearchRequest.model_validate(values)


def _fixture_response() -> dict[str, str]:
    return json.loads((FIXTURES / "web_search_response.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_exact_official_request_auth_mapping_and_response_normalization() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=_fixture_response(),
            headers={"x-request-id": "yandex-request-id"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YandexSearchProvider(_settings(), client)
        result = await provider.search(
            _context(deadline=5),
            _request(
                provider_region="213",
                safe_search=SearchSafeMode.STRICT,
                time_range=SearchTimeRange.MONTH,
            ),
        )

    assert len(calls) == 1
    assert str(calls[0].url) == "https://searchapi.api.cloud.yandex.net/v2/web/search"
    assert calls[0].method == "POST"
    assert calls[0].headers["authorization"] == "Api-Key fixture-api-key-secret"
    assert json.loads(calls[0].content) == json.loads(
        (FIXTURES / "web_search_request.json").read_text(encoding="utf-8")
    )
    assert [item.rank for item in result.results] == [1, 2]
    assert [item.title for item in result.results] == [
        "First official result",
        "Second result",
    ]
    assert result.results[0].snippet == "First bounded passage. Second passage."
    assert result.results[0].host == "first.example"
    assert result.results[0].published_at == datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert result.provider_request_id == "yandex-request-id"
    assert result.retrieved_at == NOW
    assert result.next_page_available is None


@pytest.mark.parametrize(("page", "upstream"), [(1, "0"), (2, "1")])
@pytest.mark.asyncio
async def test_application_pages_convert_to_zero_based_official_pages(
    page: int, upstream: str
) -> None:
    observed: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(json.loads(request.content))
        return httpx.Response(200, json=_fixture_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await YandexSearchProvider(_settings(), client).search(_context(), _request(page=page))

    query = observed[0]["query"]
    assert isinstance(query, dict)
    assert query["page"] == upstream


@pytest.mark.parametrize(
    ("safe", "official"),
    [
        (SearchSafeMode.OFF, "FAMILY_MODE_NONE"),
        (SearchSafeMode.MODERATE, "FAMILY_MODE_MODERATE"),
        (SearchSafeMode.STRICT, "FAMILY_MODE_STRICT"),
    ],
)
@pytest.mark.asyncio
async def test_safe_search_has_exact_official_semantics(
    safe: SearchSafeMode, official: str
) -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_fixture_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await YandexSearchProvider(_settings(), client).search(
            _context(), _request(safe_search=safe)
        )
    query = payloads[0]["query"]
    assert isinstance(query, dict) and query["familyMode"] == official


@pytest.mark.parametrize(
    ("time_range", "period"),
    [(SearchTimeRange.DAY, "PERIOD_DAY"), (SearchTimeRange.MONTH, "PERIOD_MONTH")],
)
@pytest.mark.asyncio
async def test_supported_time_ranges_map_to_current_period_contract(
    time_range: SearchTimeRange, period: str
) -> None:
    payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_fixture_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await YandexSearchProvider(_settings(), client).search(
            _context(), _request(time_range=time_range)
        )
    assert payloads[0]["period"] == period


@pytest.mark.parametrize(
    ("provider_request", "field"),
    [
        (_request(language=normalize_search_language("ru")), "language"),
        (_request(time_range=SearchTimeRange.YEAR), "time_range"),
        (_request(query="x" * 401), "query"),
        (_request(provider_region="invalid-region"), "region"),
    ],
)
@pytest.mark.asyncio
async def test_unproven_or_unsupported_mapping_is_rejected_before_network(
    provider_request: ProviderSearchRequest, field: str
) -> None:
    calls = 0

    async def handler(upstream: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_fixture_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await YandexSearchProvider(_settings(), client).search(_context(), provider_request)
    assert calls == 0
    assert caught.value.error.code == "yandex_unsupported_option"
    assert field in caught.value.error.message
    assert caught.value.stage is ExecutionStage.BEFORE_DISPATCH


def test_registry_rejects_yandex_year_language_and_long_query_before_attempt_admission() -> None:
    client = httpx.AsyncClient()
    try:
        provider = YandexSearchProvider(_settings(), client)
        registry = SearchProviderRegistry((provider,), default_provider=SearchProviderId.YANDEX)
        for query in (
            SearchQuery(query="q", language=normalize_search_language("ru")),
            SearchQuery(query="q", time_range=SearchTimeRange.YEAR),
            SearchQuery(query="x" * 401),
        ):
            with pytest.raises(ProviderResolutionError, match="не поддерживает"):
                registry.validate_capabilities(provider, query)
    finally:
        import asyncio

        asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_region_is_available_only_for_official_ru_and_tr_search_types() -> None:
    async with httpx.AsyncClient() as client:
        ru = YandexSearchProvider(_settings(search_type="SEARCH_TYPE_RU"), client)
        international = YandexSearchProvider(_settings(search_type="SEARCH_TYPE_COM"), client)
    assert ru.descriptor.capabilities.region is True
    assert international.descriptor.capabilities.region is False


@pytest.mark.asyncio
async def test_disabled_and_missing_configuration_never_dispatches() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_fixture_response())

    settings = YandexSearchSettings(enabled=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YandexSearchProvider(settings, client)
        assert provider.descriptor.enabled is False
        with pytest.raises(ProviderAttemptError) as caught:
            await provider.search(_context(), _request())
    assert calls == 0
    assert caught.value.error.code == "yandex_not_configured"
    with pytest.raises(ValidationError):
        YandexSearchSettings(enabled=True)


def test_secret_is_redacted_and_excluded_from_configuration_revision() -> None:
    settings = _settings()
    rendered = repr(settings) + str(settings)
    assert "fixture-api-key-secret" not in rendered
    first_client = httpx.AsyncClient()
    second_client = httpx.AsyncClient()
    try:
        first = YandexSearchProvider(settings, first_client).descriptor.configuration_revision
        secret_changed = YandexSearchProvider(
            _settings(api_key="different-secret"), second_client
        ).descriptor.configuration_revision
    finally:
        import asyncio

        asyncio.run(first_client.aclose())
        asyncio.run(second_client.aclose())
    assert first == secret_changed
    assert "fixture-api-key-secret" not in first


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"not-json", "yandex_malformed_response"),
        (b'{"rawData":"not base64!"}', "yandex_malformed_response"),
        (
            json.dumps({"rawData": base64.b64encode(b"<broken>").decode()}).encode(),
            "yandex_malformed_response",
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_json_base64_and_xml_are_terminal(payload: bytes, code: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, content=payload, headers={"x-request-id": "safe-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await YandexSearchProvider(_settings(), client).search(_context(), _request())
    assert caught.value.error.code == code
    assert caught.value.error.retryable is False
    assert caught.value.error.details is None
    assert caught.value.stage is ExecutionStage.TERMINAL_KNOWN
    assert caught.value.provider_request_id == "safe-id"


@pytest.mark.parametrize(
    ("status", "code", "category", "retryable"),
    [
        (400, "yandex_request_rejected", ErrorCategory.VALIDATION, False),
        (401, "yandex_auth_rejected", ErrorCategory.AUTHENTICATION, False),
        (403, "yandex_auth_rejected", ErrorCategory.AUTHENTICATION, False),
        (429, "yandex_rate_limited", ErrorCategory.RATE_LIMITED, True),
        (503, "yandex_upstream_error", ErrorCategory.UPSTREAM, True),
    ],
)
@pytest.mark.asyncio
async def test_http_errors_are_normalized_without_body_or_secret(
    status: int, code: str, category: ErrorCategory, retryable: bool
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            status,
            content=b"raw provider diagnostic",
            headers={"x-request-id": "safe-id", "retry-after": "9"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await YandexSearchProvider(_settings(), client).search(_context(), _request())
    assert caught.value.error.code == code
    assert caught.value.error.category is category
    assert caught.value.error.retryable is retryable
    rendered = str(caught.value.error.model_dump())
    assert "raw provider" not in rendered and "fixture-api-key-secret" not in rendered
    assert caught.value.stage is ExecutionStage.TERMINAL_KNOWN


@pytest.mark.parametrize(
    ("failure_kind", "stage", "code"),
    [
        ("connect", ExecutionStage.BEFORE_DISPATCH, "yandex_connect_failed"),
        ("read", ExecutionStage.RESPONSE_LOST, "yandex_response_lost"),
    ],
)
@pytest.mark.asyncio
async def test_transport_evidence_is_conservative(
    failure_kind: str, stage: ExecutionStage, code: str
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure_kind == "connect":
            raise httpx.ConnectError("offline", request=request)
        raise httpx.ReadTimeout("lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as caught:
            await YandexSearchProvider(_settings(), client).search(_context(), _request())
    assert calls == 1
    assert caught.value.error.code == code
    assert caught.value.stage is stage


@pytest.mark.asyncio
async def test_response_size_bound_applies_before_and_after_base64_decode() -> None:
    oversized_json = b"x" * 1025
    oversized_xml = base64.b64encode(b"x" * 1025).decode()
    responses = [
        httpx.Response(200, content=oversized_json),
        httpx.Response(200, json={"rawData": oversized_xml}),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return responses.pop(0)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YandexSearchProvider(_settings(max_response_bytes=1024), client)
        for _ in range(2):
            with pytest.raises(ProviderAttemptError) as caught:
                await provider.search(_context(), _request())
            assert caught.value.error.code == "yandex_response_too_large"


@pytest.mark.parametrize(("error_code", "empty"), [("15", True), ("18", False)])
@pytest.mark.asyncio
async def test_xml_provider_errors_distinguish_empty_results(error_code: str, empty: bool) -> None:
    xml = (
        f'<yandexsearch><response><error code="{error_code}">raw</error></response></yandexsearch>'
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json={"rawData": base64.b64encode(xml.encode()).decode()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = YandexSearchProvider(_settings(), client)
        if empty:
            result = await provider.search(_context(), _request())
            assert result.results == ()
        else:
            with pytest.raises(ProviderAttemptError) as caught:
                await provider.search(_context(), _request())
            assert caught.value.error.code == "yandex_search_error"


@pytest.mark.asyncio
async def test_malformed_result_item_is_omitted_with_safe_warning() -> None:
    xml = b"""<yandexsearch><response><results><grouping><group><doc>
      <url>javascript:bad</url><title>bad</title></doc></group><group><doc>
      <url>https://valid.example</url><title>valid</title>
      </doc></group></grouping></results></response></yandexsearch>"""

    async def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json={"rawData": base64.b64encode(xml).decode()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await YandexSearchProvider(_settings(), client).search(_context(), _request())
    assert [item.title for item in result.results] == ["valid"]
    assert [warning.code for warning in result.warnings] == ["malformed_provider_item"]


@pytest.mark.asyncio
async def test_expired_deadline_and_non_ru_region_prevent_dispatch() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_fixture_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderAttemptError) as deadline:
            await YandexSearchProvider(_settings(), client).search(_context(deadline=0), _request())
        with pytest.raises(ProviderAttemptError) as region:
            await YandexSearchProvider(_settings(search_type="SEARCH_TYPE_COM"), client).search(
                _context(), _request(provider_region="213")
            )
    assert calls == 0
    assert deadline.value.stage is ExecutionStage.BEFORE_DISPATCH
    assert region.value.error.code == "yandex_unsupported_option"
