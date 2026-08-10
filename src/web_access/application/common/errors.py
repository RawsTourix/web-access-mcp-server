"""Normalized application and public error contracts."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    POLICY = "policy"
    PERMISSION = "permission"
    AUTHENTICATION = "authentication"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    RATE_LIMITED = "rate_limited"
    CAPACITY = "capacity"
    UPSTREAM = "upstream"
    TIMEOUT = "timeout"
    INFRASTRUCTURE = "infrastructure"
    RESOURCE_LOST = "resource_lost"
    CANCELLED = "cancelled"
    UNKNOWN_OUTCOME = "unknown_outcome"
    INTERNAL = "internal"


MachineCode = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]


def _validate_details_size(details: dict[str, JsonValue] | None) -> dict[str, JsonValue] | None:
    if details is not None and len(json.dumps(details, ensure_ascii=False).encode()) > 8192:
        raise ValueError("details exceed 8 KiB")
    return details


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(max_length=256)
    code: MachineCode
    message: str = Field(min_length=1, max_length=1024)


class OperationError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ErrorCategory
    code: MachineCode
    message: str = Field(min_length=1, max_length=1024)
    retryable: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=0)
    fields: tuple[FieldError, ...] = Field(default=(), max_length=32)
    details: dict[str, JsonValue] | None = None

    _details_size = field_validator("details")(_validate_details_size)


PublicError = OperationError


class AuthenticationFailure(StrEnum):
    MISSING_CREDENTIALS = "missing_credentials"
    INVALID_CREDENTIALS = "invalid_credentials"
    EXPIRED_CREDENTIALS = "expired_credentials"
    CREDENTIAL_DISABLED = "credential_disabled"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    OWNER_ACCESS_DENIED = "owner_access_denied"


class AuthorizationError(PermissionError):
    """Safe application-side authorization failure."""

    def __init__(self, code: AuthenticationFailure, message: str) -> None:
        if not re.fullmatch(r"[a-z0-9_]+", code.value):
            raise ValueError("invalid authorization error code")
        self.code = code
        super().__init__(message)


class ErrorEnvelope(BaseModel):
    """Common REST-level error body used by the transport adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: PublicError
