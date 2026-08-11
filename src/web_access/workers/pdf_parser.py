"""Allowlisted isolated PDF native-text handler; this is the only pypdf import path."""

from __future__ import annotations

import base64
import io
import json

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

from web_access.application.common.hints import (
    StructuredHint,
    Warning,
    advanced_processing_may_be_required,
)
from web_access.application.content.isolation import (
    IsolatedParserResult,
    IsolatedRepresentation,
)
from web_access.domain.content import ContentRepresentationKind


def parse_pdf(data: bytes, parameters: dict[str, object]) -> IsolatedParserResult:
    try:
        limits = _limits(parameters)
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return _failure("encrypted_content", "Encrypted PDF Content is not parsed.")
        page_count = len(reader.pages)
        if page_count > limits["max_pages"]:
            return _failure("pdf_page_limit", "PDF page count exceeds its configured limit.")

        warnings: list[Warning] = []
        pages: list[dict[str, object]] = []
        extracted: list[str] = []
        total_chars = 0
        for page_number, page in enumerate(reader.pages, start=1):
            if (
                _raw_content_bytes(page.get("/Contents"), limits["max_content_stream_bytes"])
                > limits["max_content_stream_bytes"]
            ):
                return _failure(
                    "pdf_content_stream_limit",
                    "PDF encoded content streams exceed their configured limit.",
                )
            if _resource_entries(page.get("/Resources")) > limits["max_resource_entries"]:
                return _failure(
                    "pdf_resource_limit",
                    "PDF page resources exceed their configured limit.",
                )
            text = (page.extract_text() or "").replace("\x00", "")
            if len(text) > limits["max_page_chars"]:
                text = text[: limits["max_page_chars"]]
                _warn_once(
                    warnings,
                    "pdf_page_text_truncated",
                    "PDF page text reached its configured character bound.",
                )
            remaining = limits["max_output_chars"] - total_chars
            if remaining <= 0:
                text = ""
                _warn_once(
                    warnings,
                    "pdf_text_truncated",
                    "PDF native text reached its configured total bound.",
                )
            elif len(text) > remaining:
                text = text[:remaining]
                _warn_once(
                    warnings,
                    "pdf_text_truncated",
                    "PDF native text reached its configured total bound.",
                )
            total_chars += len(text)
            extracted.append(text)
            pages.append({"page": page_number, "text_chars": len(text)})

        metadata = _metadata(reader.metadata, limits["max_metadata_chars"])
        structure = json.dumps(
            {
                "schema_revision": "content-pdf-structure-v1",
                "page_count": page_count,
                "metadata": metadata,
                "pages": pages,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        representations: list[IsolatedRepresentation] = [
            _representation(
                ContentRepresentationKind.STRUCTURED,
                "application/vnd.web-access.content+json",
                "content-pdf-structure-v1",
                structure,
            )
        ]
        combined = "\n\n\f\n\n".join(extracted).strip()
        hints: tuple[StructuredHint, ...] = ()
        if combined:
            representations.insert(
                0,
                _representation(
                    ContentRepresentationKind.TEXT,
                    "text/plain; charset=utf-8",
                    "content-pdf-text-v1",
                    combined.encode(),
                ),
            )
        else:
            warnings.append(
                Warning(
                    code="pdf_native_text_unavailable",
                    message="PDF не содержит извлекаемого нативного текстового слоя.",
                )
            )
            hints = (advanced_processing_may_be_required(),)
        return IsolatedParserResult(
            ok=True,
            representations=tuple(representations),
            warnings=tuple(warnings),
            hints=hints,
        )
    except (PdfReadError, OSError, ValueError, TypeError):
        return _failure("malformed_pdf", "PDF Content is malformed or unsupported.")


def _limits(parameters: dict[str, object]) -> dict[str, int]:
    names = (
        "max_pages",
        "max_page_chars",
        "max_output_chars",
        "max_metadata_chars",
        "max_content_stream_bytes",
        "max_resource_entries",
    )
    result: dict[str, int] = {}
    for name in names:
        value = parameters.get(name)
        if not isinstance(value, int) or value < 1:
            raise ValueError("invalid PDF parser limit")
        result[name] = value
    return result


def _resolve(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _raw_content_bytes(value: object, limit: int) -> int:
    total = 0
    visited: set[tuple[int, int]] = set()
    pending = [value]
    objects = 0
    while pending:
        current = pending.pop()
        objects += 1
        if objects > 10_000:
            return limit + 1
        if isinstance(current, IndirectObject):
            identity = (current.idnum, current.generation)
            if identity in visited:
                continue
            visited.add(identity)
        resolved = _resolve(current)
        if isinstance(resolved, ArrayObject):
            pending.extend(resolved)
        elif isinstance(resolved, StreamObject):
            raw = getattr(resolved, "_data", b"")
            total += len(raw) if isinstance(raw, bytes) else 0
            if total > limit:
                return total
    return total


def _resource_entries(value: object) -> int:
    resolved = _resolve(value)
    if not isinstance(resolved, DictionaryObject):
        return 0
    total = len(resolved)
    for child in resolved.values():
        nested = _resolve(child)
        if isinstance(nested, DictionaryObject):
            total += len(nested)
    return total


def _metadata(value: object, limit: int) -> dict[str, str]:
    if not isinstance(value, DictionaryObject):
        return {}
    result: dict[str, str] = {}
    for key, item in list(value.items())[:32]:
        result[str(key)[:128]] = str(item)[:limit]
    return result


def _representation(
    kind: ContentRepresentationKind,
    media_type: str,
    schema_revision: str,
    data: bytes,
) -> IsolatedRepresentation:
    return IsolatedRepresentation(
        representation=kind,
        media_type=media_type,
        schema_revision=schema_revision,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def _failure(code: str, message: str) -> IsolatedParserResult:
    return IsolatedParserResult(ok=False, error_code=code, error_message=message)


def _warn_once(warnings: list[Warning], code: str, message: str) -> None:
    if not any(warning.code == code for warning in warnings):
        warnings.append(Warning(code=code, message=message))
