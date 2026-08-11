"""Warnings and trusted structured recommendations."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from web_access.application.common.errors import _validate_details_size

HintCode = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]


class Warning(BaseModel):
    """A limitation of a result already obtained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: HintCode
    message: str = Field(min_length=1, max_length=1024)
    details: dict[str, JsonValue] | None = None

    _details_size = field_validator("details")(_validate_details_size)


class StructuredHint(BaseModel):
    """Trusted recommendation that never performs the recommended action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: HintCode
    message: str = Field(min_length=1, max_length=1024)
    related_tool: str | None = Field(default=None, max_length=128)
    related_capability: str | None = Field(default=None, max_length=128)
    details: dict[str, JsonValue] | None = None

    _details_size = field_validator("details")(_validate_details_size)


def browser_may_be_required() -> StructuredHint:
    """Create the trusted recommendation for a server-detected HTML script shell."""

    return StructuredHint(
        code="browser_may_be_required",
        message="Структура script shell указывает, что отображаемое содержимое может отличаться.",
        related_capability="browser",
    )


def advanced_processing_may_be_required() -> StructuredHint:
    """Create the trusted recommendation for content without a native text layer."""

    return StructuredHint(
        code="advanced_processing_may_be_required",
        message=(
            "Для Content без нативного текста может потребоваться отдельно разрешённая обработка."
        ),
        related_capability="advanced_content_processing",
    )


def native_processing_unsupported() -> StructuredHint:
    """Create the trusted recommendation for a format outside the native parser registry."""

    return StructuredHint(
        code="native_processing_unsupported",
        message="Для обнаруженного формата не зарегистрирован L1 Native Parser.",
        related_capability="native_content_processing",
    )
