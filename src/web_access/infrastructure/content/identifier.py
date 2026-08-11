"""Bounded descriptor-based Content identification for L0 inspection."""

from __future__ import annotations

import codecs
import csv
import io
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PurePath

from web_access.application.common.hints import Warning
from web_access.application.content.models import ContentInspection
from web_access.domain.content import ContentFormat, ParserAvailability

EvidenceDetector = Callable[[bytes], bool]

_HTML = re.compile(rb"<\s*(?:!doctype\s+html|html|head|body|title|meta|article)\b", re.I)
_XML = re.compile(rb"^\s*(?:<\?xml\b[^>]*\?>\s*)?<([A-Za-z_][\w:.-]*)\b", re.S)
_MIME_FORMATS = {
    "text/html": ContentFormat.HTML,
    "application/xhtml+xml": ContentFormat.HTML,
    "text/plain": ContentFormat.TEXT,
    "application/json": ContentFormat.JSON,
    "text/json": ContentFormat.JSON,
    "application/xml": ContentFormat.XML,
    "text/xml": ContentFormat.XML,
    "text/csv": ContentFormat.CSV,
    "application/csv": ContentFormat.CSV,
    "application/pdf": ContentFormat.PDF,
}


@dataclass(frozen=True, slots=True)
class IdentificationDescriptor:
    format: ContentFormat
    media_type: str
    suffixes: frozenset[str]
    declared_media_types: frozenset[str]
    evidence: EvidenceDetector
    priority: int


@dataclass(frozen=True, slots=True)
class IdentificationMatch:
    format: ContentFormat
    media_type: str
    encoding: str | None


class ContentIdentificationRegistry:
    def __init__(self, descriptors: Iterable[IdentificationDescriptor]) -> None:
        self._descriptors = tuple(descriptors)
        formats = [descriptor.format for descriptor in self._descriptors]
        if not self._descriptors or len(formats) != len(set(formats)):
            raise ValueError("Content identification descriptors must have unique formats")

    def identify(
        self,
        data: bytes,
        *,
        declared_media_type: str | None,
        source_filename: str | None,
    ) -> IdentificationMatch:
        declared = _normalize_media_type(declared_media_type)
        suffix = PurePath(source_filename).suffix.lower() if source_filename else ""
        candidates: list[tuple[int, IdentificationDescriptor]] = []
        for descriptor in self._descriptors:
            if not descriptor.evidence(data):
                continue
            score = descriptor.priority
            if declared in descriptor.declared_media_types:
                score += 20
            if suffix in descriptor.suffixes:
                score += 10
            candidates.append((score, descriptor))
        if not candidates:
            return IdentificationMatch(ContentFormat.UNKNOWN, "application/octet-stream", None)
        descriptor = max(candidates, key=lambda candidate: candidate[0])[1]
        encoding = _observed_encoding(data) if descriptor.format is not ContentFormat.PDF else None
        return IdentificationMatch(descriptor.format, descriptor.media_type, encoding)


class RegistryContentIdentifier:
    def __init__(
        self,
        registry: ContentIdentificationRegistry | None = None,
        *,
        available_formats: frozenset[ContentFormat] = frozenset(),
    ) -> None:
        self._registry = registry or default_identification_registry()
        self._available_formats = available_formats

    async def inspect(
        self,
        data: bytes,
        *,
        size_bytes: int,
        sha256: str,
        declared_media_type: str | None,
        source_filename: str | None,
    ) -> ContentInspection:
        match = self._registry.identify(
            data,
            declared_media_type=declared_media_type,
            source_filename=source_filename,
        )
        warnings: tuple[Warning, ...] = ()
        declared = _normalize_media_type(declared_media_type)
        declared_format = _MIME_FORMATS.get(declared) if declared is not None else None
        if declared_format is not None and declared_format is not match.format:
            warnings = (
                Warning(
                    code="declared_content_type_mismatch",
                    message="Declared Content-Type does not match bounded content evidence.",
                    details={
                        "declared_format": declared_format.value,
                        "detected_format": match.format.value,
                    },
                ),
            )
        availability = (
            ParserAvailability.AVAILABLE
            if match.format in self._available_formats
            else ParserAvailability.UNSUPPORTED
        )
        return ContentInspection(
            size_bytes=size_bytes,
            sha256=sha256,
            declared_media_type=_normalize_media_type(declared_media_type),
            detected_media_type=match.media_type,
            detected_format=match.format,
            source_filename=_safe_filename(source_filename),
            encoding=match.encoding,
            parser_availability=availability,
            warnings=warnings,
        )


def default_identification_registry() -> ContentIdentificationRegistry:
    return ContentIdentificationRegistry(
        (
            IdentificationDescriptor(
                ContentFormat.PDF,
                "application/pdf",
                frozenset({".pdf"}),
                frozenset({"application/pdf"}),
                lambda data: b"%PDF-" in data[:1024],
                100,
            ),
            IdentificationDescriptor(
                ContentFormat.HTML,
                "text/html",
                frozenset({".html", ".htm", ".xhtml"}),
                frozenset({"text/html", "application/xhtml+xml"}),
                lambda data: _HTML.search(data[:16384]) is not None,
                90,
            ),
            IdentificationDescriptor(
                ContentFormat.JSON,
                "application/json",
                frozenset({".json"}),
                frozenset({"application/json", "text/json"}),
                _is_json,
                80,
            ),
            IdentificationDescriptor(
                ContentFormat.XML,
                "application/xml",
                frozenset({".xml"}),
                frozenset({"application/xml", "text/xml"}),
                _is_xml,
                70,
            ),
            IdentificationDescriptor(
                ContentFormat.CSV,
                "text/csv",
                frozenset({".csv", ".tsv"}),
                frozenset({"text/csv", "application/csv"}),
                _is_csv,
                60,
            ),
            IdentificationDescriptor(
                ContentFormat.TEXT,
                "text/plain",
                frozenset({".txt", ".md", ".log"}),
                frozenset({"text/plain"}),
                _is_text,
                10,
            ),
        )
    )


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    return normalized or None


def _decode_text(data: bytes) -> str | None:
    encoding = _observed_encoding(data)
    if encoding is None:
        return None
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return None


def _observed_encoding(data: bytes) -> str | None:
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if data.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "utf-8"


def _is_json(data: bytes) -> bool:
    text = _decode_text(data)
    if text is None or not text.lstrip().startswith(("{", "[")):
        return False
    try:
        json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return False
    return True


def _is_xml(data: bytes) -> bool:
    sample = data[:65536]
    match = _XML.search(sample)
    return match is not None and match.group(1).lower() != b"html"


def _is_csv(data: bytes) -> bool:
    text = _decode_text(data[:65536])
    if text is None:
        return False
    lines = [line for line in text.splitlines()[:20] if line.strip()]
    if len(lines) < 2:
        return False
    sample = "\n".join(lines)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        rows = list(csv.reader(io.StringIO(sample), dialect=dialect))
    except csv.Error:
        return False
    widths = {len(row) for row in rows}
    return len(widths) == 1 and next(iter(widths), 0) >= 2


def _is_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    text = _decode_text(data[:65536])
    if text is None:
        return False
    printable = sum(character.isprintable() or character in "\r\n\t" for character in text)
    return printable / max(1, len(text)) >= 0.85


def _safe_filename(value: str | None) -> str | None:
    if value is None:
        return None
    safe = "".join(
        "_" if character in {"/", "\\"} or ord(character) < 32 else character for character in value
    ).strip(" .")
    return safe[:255] or None
