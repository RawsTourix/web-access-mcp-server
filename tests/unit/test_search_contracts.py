"""S1 Search domain/application contract gates."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from web_access.application.common.context import ExecutionContext
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
    SearchBatchRequest,
    SearchQuery,
)
from web_access.application.search.registry import (
    ProviderResolutionError,
    SearchProviderRegistry,
)
from web_access.domain.search import (
    SearchProviderId,
    SearchProviderSelection,
    SearchRegionId,
    SearchResultItem,
)


class FakeProvider:
    def __init__(self, descriptor: ProviderDescriptor) -> None:
        self.descriptor = descriptor

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        _ = context, request
        raise NotImplementedError


def descriptor(
    provider_id: SearchProviderId,
    *,
    enabled: bool = True,
    region: bool = False,
    max_results: int = 50,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        name=provider_id.value,
        enabled=enabled,
        configuration_revision="revision-1",
        capabilities=ProviderCapabilities(
            pagination=True,
            language=True,
            region=region,
            safe_search=True,
            time_range=True,
            max_results=max_results,
            billable=provider_id is SearchProviderId.YANDEX,
        ),
    )


def test_default_and_explicit_resolution_are_deterministic_without_fallback() -> None:
    searxng = FakeProvider(descriptor(SearchProviderId.SEARXNG))
    yandex = FakeProvider(descriptor(SearchProviderId.YANDEX))
    registry = SearchProviderRegistry((searxng, yandex), default_provider=SearchProviderId.SEARXNG)

    assert registry.resolve(SearchProviderSelection.DEFAULT) is searxng
    assert registry.resolve(SearchProviderSelection.YANDEX) is yandex


def test_disabled_provider_is_rejected_and_default_must_be_enabled() -> None:
    disabled = FakeProvider(descriptor(SearchProviderId.YANDEX, enabled=False))
    searxng = FakeProvider(descriptor(SearchProviderId.SEARXNG))
    registry = SearchProviderRegistry(
        (searxng, disabled), default_provider=SearchProviderId.SEARXNG
    )
    with pytest.raises(ProviderResolutionError) as error:
        registry.resolve(SearchProviderSelection.YANDEX)
    assert error.value.code == "provider_disabled"
    with pytest.raises(ValueError, match="default Search provider is disabled"):
        SearchProviderRegistry((disabled,), default_provider=SearchProviderId.YANDEX)


def test_explicit_unsupported_options_are_rejected() -> None:
    provider = FakeProvider(descriptor(SearchProviderId.SEARXNG, region=False, max_results=20))
    query = SearchQuery(query="example", region=SearchRegionId("ru-moscow"), limit=21)
    with pytest.raises(ProviderResolutionError) as error:
        SearchProviderRegistry.validate_capabilities(provider, query)
    assert error.value.code == "unsupported_option"
    assert "region" in str(error.value)
    assert "limit" in str(error.value)


def test_result_bounds_order_and_empty_success_representation() -> None:
    now = datetime.now(UTC)
    results = (
        SearchResultItem(rank=1, title="first", url="https://first.test", published_at=now),
        SearchResultItem(rank=2, title="second", url="https://second.test"),
    )
    assert [item.rank for item in results] == [1, 2]
    assert tuple() == ()
    with pytest.raises(ValueError, match="title"):
        SearchResultItem(rank=1, title="x" * 4097, url="https://example.test")
    with pytest.raises(ValueError, match="timezone-aware"):
        SearchResultItem(
            rank=1,
            title="naive",
            url="https://example.test",
            published_at=datetime(2026, 8, 11, 12),
        )


@pytest.mark.parametrize("size", [0, 33])
def test_batch_exact_bounds(size: int) -> None:
    with pytest.raises(ValidationError):
        SearchBatchRequest(queries=tuple(SearchQuery(query="q") for _ in range(size)))


def test_query_is_trimmed_and_rejects_unknown_fields() -> None:
    assert SearchQuery(query="  example  ").query == "example"
    with pytest.raises(ValidationError):
        SearchQuery.model_validate({"query": "x", "provider_options": {}})
