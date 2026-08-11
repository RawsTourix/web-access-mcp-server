"""Capability registry selecting parsers only by detected Content format."""

from __future__ import annotations

from collections.abc import Iterable

from web_access.application.content.models import ContentInspection
from web_access.application.content.ports import NativeParser
from web_access.domain.content import ContentFormat


class ContentNativeParserRegistry:
    def __init__(self, parsers: Iterable[NativeParser]) -> None:
        self._by_format: dict[ContentFormat, NativeParser] = {}
        self._by_capability: dict[str, NativeParser] = {}
        for parser in parsers:
            descriptor = parser.descriptor
            if descriptor.capability in self._by_capability:
                raise ValueError("duplicate native parser capability")
            self._by_capability[descriptor.capability] = parser
            for supported_format in descriptor.supported_formats:
                if supported_format in self._by_format:
                    raise ValueError("multiple native parsers claim one Content format")
                self._by_format[supported_format] = parser

    @property
    def available_formats(self) -> frozenset[ContentFormat]:
        return frozenset(self._by_format)

    def select(self, inspection: ContentInspection) -> NativeParser | None:
        return self._by_format.get(inspection.detected_format)
