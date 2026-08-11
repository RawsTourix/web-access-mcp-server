"""S2 language, region, and Search configuration gates."""

import pytest
from pydantic import ValidationError

from web_access.application.search.language import normalize_search_language
from web_access.application.search.models import SearchQuery, SearchRegionEntry, SearchRegionMapping
from web_access.application.search.registry import ProviderResolutionError, SearchRegionRegistry
from web_access.core.config import SearchSettings, Settings
from web_access.domain.search import SearchLanguage, SearchProviderId, SearchRegionId


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("ru", "ru"), ("EN", "en"), ("ru-ru", "ru-RU"), ("en-gb", "en-GB")],
)
def test_language_is_validated_and_normalized(raw: str, normalized: str) -> None:
    assert normalize_search_language(raw).value == normalized
    assert SearchQuery.model_validate({"query": "q", "language": raw}).language == SearchLanguage(
        normalized
    )


@pytest.mark.parametrize("raw", ["", "not_a_tag", "x" * 65, "ru--RU"])
def test_malformed_language_is_rejected(raw: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        SearchQuery.model_validate({"query": "q", "language": raw})


def test_region_registry_is_exact_and_missing_mapping_is_rejected() -> None:
    registry = SearchRegionRegistry(
        (
            SearchRegionEntry(
                region_id=SearchRegionId("ru-moscow"),
                label="Moscow",
                mappings=(
                    SearchRegionMapping(provider_id=SearchProviderId.YANDEX, provider_region="213"),
                ),
            ),
        )
    )
    assert registry.provider_region("ru-moscow", SearchProviderId.YANDEX) == "213"
    with pytest.raises(ProviderResolutionError) as missing:
        registry.provider_region("ru-moscow", SearchProviderId.SEARXNG)
    assert missing.value.code == "unsupported_region"
    with pytest.raises(ProviderResolutionError) as unknown:
        registry.provider_region("moscow", SearchProviderId.YANDEX)
    assert unknown.value.code == "unknown_region"


def test_region_revision_is_deterministic_and_changes_with_mapping() -> None:
    def revision(provider_region: str) -> str:
        return SearchRegionRegistry(
            (
                SearchRegionEntry(
                    region_id=SearchRegionId("ru-moscow"),
                    label="Moscow",
                    mappings=(
                        SearchRegionMapping(
                            provider_id=SearchProviderId.YANDEX,
                            provider_region=provider_region,
                        ),
                    ),
                ),
            )
        ).revision

    assert revision("213") == revision("213")
    assert revision("213") != revision("214")
    assert "213" not in revision("213")


def test_config_rejects_duplicate_regions_mappings_and_providers() -> None:
    with pytest.raises(ValidationError, match="duplicate Search provider"):
        SearchSettings(provider_order=("searxng", "searxng"))
    with pytest.raises(ValidationError, match="duplicate Search region"):
        SearchSettings.model_validate(
            {
                "regions": [
                    {"region_id": "ru", "label": "one"},
                    {"region_id": "ru", "label": "two"},
                ]
            }
        )
    with pytest.raises(ValidationError, match="duplicate provider mapping"):
        SearchSettings.model_validate(
            {
                "regions": [
                    {
                        "region_id": "ru",
                        "label": "Russia",
                        "mappings": [
                            {"provider_id": "yandex", "provider_region": "225"},
                            {"provider_id": "yandex", "provider_region": "213"},
                        ],
                    }
                ]
            }
        )


def test_yandex_config_is_secret_safe_and_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="folder_id and api_key"):
        SearchSettings.model_validate({"yandex": {"enabled": True}})
    settings = SearchSettings.model_validate(
        {
            "yandex": {
                "enabled": True,
                "folder_id": "folder",
                "api_key": "top-secret-api-key",
            }
        }
    )
    assert "top-secret-api-key" not in repr(settings)
    assert "top-secret-api-key" not in settings.provider_revision("yandex")


def test_production_rejects_implicit_searxng_endpoint() -> None:
    with pytest.raises(ValidationError, match="SearXNG endpoint"):
        Settings.model_validate(
            {
                "app": {"environment": "production"},
                "auth": {
                    "principals": [
                        {
                            "principal_id": "agent",
                            "tokens": ["token-with-enough-entropy"],
                            "scopes": ["*"],
                        }
                    ]
                },
                "database": {"url": "postgresql+asyncpg://u:p@db/db"},
                "redis": {"url": "redis://redis:6379/0"},
                "content_store": {"root": "/var/lib/web-access/content"},
            }
        )
