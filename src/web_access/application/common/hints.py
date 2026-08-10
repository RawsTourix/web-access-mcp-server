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
