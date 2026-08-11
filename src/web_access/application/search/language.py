"""BCP 47 normalization at the application boundary."""

from __future__ import annotations

import re

import langcodes

from web_access.domain.search import SearchLanguage

_LANGUAGE_TAG_INPUT = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")


def normalize_search_language(value: str) -> SearchLanguage:
    """Parse and normalize caller input before constructing the domain value."""

    raw = value.strip()
    if (
        not 1 <= len(raw) <= 64
        or _LANGUAGE_TAG_INPUT.fullmatch(raw) is None
        or not langcodes.tag_is_valid(raw)
    ):
        raise ValueError("invalid language tag")
    return SearchLanguage(langcodes.Language.get(raw).to_tag())
