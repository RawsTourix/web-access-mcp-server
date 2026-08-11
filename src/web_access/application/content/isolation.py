"""Versioned JSON-only isolated parser protocol models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from web_access.application.common.hints import StructuredHint, Warning
from web_access.domain.content import ContentRepresentationKind


class IsolatedParserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["web-access-parser-request-v1"] = "web-access-parser-request-v1"
    parser_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    input_file: Literal["input.bin"] = "input.bin"
    max_input_bytes: int = Field(ge=0, le=64 * 1024 * 1024)
    max_output_bytes: int = Field(ge=1, le=128 * 1024 * 1024)
    cpu_seconds: int = Field(ge=1, le=120)
    memory_bytes: int = Field(ge=64 * 1024 * 1024, le=8 * 1024 * 1024 * 1024)
    open_files: int = Field(ge=8, le=256)
    processes: int = Field(ge=1, le=8)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class IsolatedRepresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    representation: ContentRepresentationKind
    media_type: str = Field(min_length=1, max_length=255)
    schema_revision: str = Field(min_length=1, max_length=128)
    data_base64: str = Field(max_length=128 * 1024 * 1024)


class IsolatedParserResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["web-access-parser-result-v1"] = "web-access-parser-result-v1"
    ok: bool
    representations: tuple[IsolatedRepresentation, ...] = Field(default=(), max_length=8)
    warnings: tuple[Warning, ...] = Field(default=(), max_length=16)
    hints: tuple[StructuredHint, ...] = Field(default=(), max_length=16)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=64)
    error_message: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_status(self) -> IsolatedParserResult:
        if self.ok:
            if not self.representations or self.error_code is not None:
                raise ValueError("successful parser result requires representations only")
        elif self.error_code is None or self.representations:
            raise ValueError("failed parser result requires a bounded error only")
        return self
