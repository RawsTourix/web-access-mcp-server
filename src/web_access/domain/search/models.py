"""Stable provider-neutral Search values and invariants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

_REGION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NORMALIZED_LANGUAGE_TAG = re.compile(
    r"^[a-z]{2,8}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-[A-Za-z0-9]{1,8})*$"
)


class SearchProviderId(StrEnum):
    SEARXNG = "searxng"
    YANDEX = "yandex"


class SearchProviderSelection(StrEnum):
    DEFAULT = "default"
    SEARXNG = "searxng"
    YANDEX = "yandex"


class SearchSafeMode(StrEnum):
    OFF = "off"
    MODERATE = "moderate"
    STRICT = "strict"


class SearchTimeRange(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True, slots=True)
class SearchLanguage:
    """Normalized provider-independent language tag."""

    value: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.value) <= 64:
            raise ValueError("language tag length must be between 1 and 64")
        if _NORMALIZED_LANGUAGE_TAG.fullmatch(self.value) is None:
            raise ValueError("invalid language tag")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SearchRegionId:
    value: str

    def __post_init__(self) -> None:
        if _REGION_ID.fullmatch(self.value) is None:
            raise ValueError("invalid Search region ID")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    rank: int
    title: str
    url: str
    snippet: str | None = None
    host: str | None = None
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be positive")
        for value, maximum, field in (
            (self.title, 4096, "title"),
            (self.url, 8192, "url"),
            (self.snippet, 8192, "snippet"),
            (self.host, 1024, "host"),
        ):
            if value is not None and len(value) > maximum:
                raise ValueError(f"{field} exceeds public Search bound")
