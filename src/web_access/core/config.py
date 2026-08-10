"""Central typed configuration owned by the composition root."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


NonEmptyText = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@*\-]+$")]


class PrincipalSettings(BaseModel):
    """One configured service principal and its active rotation credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: NonEmptyText
    tokens: tuple[SecretStr, ...] = Field(min_length=1)
    scopes: frozenset[NonEmptyText] = Field(min_length=1)

    @field_validator("tokens")
    @classmethod
    def validate_tokens(cls, tokens: tuple[SecretStr, ...]) -> tuple[SecretStr, ...]:
        raw = [token.get_secret_value() for token in tokens]
        if any(not token.strip() for token in raw):
            raise ValueError("bearer tokens must not be empty")
        if any(len(token) < 16 for token in raw):
            raise ValueError("bearer tokens must contain at least 16 characters")
        if len(set(raw)) != len(raw):
            raise ValueError("duplicate bearer token within principal")
        return tokens


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: Environment = Environment.DEVELOPMENT
    service_name: NonEmptyText = "web-access"
    debug: bool = False
    host: str = "0.0.0.0"  # noqa: S104 -- container listener is an explicit deployment setting.
    port: int = Field(default=8000, ge=1, le=65535)


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principals: tuple[PrincipalSettings, ...] = ()
    principals_file: Path | None = None
    diagnostic_scope: NonEmptyText = "admin:read"

    @model_validator(mode="after")
    def load_and_validate_registry(self) -> Self:
        if self.principals and self.principals_file is not None:
            raise ValueError("auth principals and principals_file are mutually exclusive")
        principals = self.principals
        if self.principals_file is not None:
            try:
                raw = json.loads(self.principals_file.read_text(encoding="utf-8"))
                principals = tuple(PrincipalSettings.model_validate(item) for item in raw)
            except (OSError, json.JSONDecodeError, TypeError) as error:
                raise ValueError("unable to load auth principals file") from error
            object.__setattr__(self, "principals", principals)

        principal_ids = [principal.principal_id for principal in principals]
        if len(set(principal_ids)) != len(principal_ids):
            raise ValueError("duplicate principal_id")
        credentials = [
            token.get_secret_value() for principal in principals for token in principal.tokens
        ]
        if len(set(credentials)) != len(credentials):
            raise ValueError("bearer token is ambiguous across principals")
        return self


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://web_access:development-only@localhost:5432/web_access"
    )
    pool_size: int = Field(default=5, ge=1, le=100)
    pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class RedisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    namespace: NonEmptyText = "web-access:v1"
    socket_timeout_seconds: float = Field(default=2.0, gt=0, le=30)


class ContentStoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path = Path(".content")
    chunk_size: int = Field(default=64 * 1024, ge=4096, le=4 * 1024 * 1024)

    @field_validator("root")
    @classmethod
    def validate_root(cls, root: Path) -> Path:
        if not str(root).strip() or "\x00" in str(root):
            raise ValueError("invalid ContentStore root")
        return root


class ObservabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    log_format: Literal["json", "console"] = "json"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    tracing_enabled: bool = False
    otlp_endpoint: str | None = None


class SecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id_max_length: int = Field(default=128, ge=16, le=512)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class Settings(BaseSettings):
    """Single environment-owned settings graph."""

    model_config = SettingsConfigDict(
        env_prefix="WEB_ACCESS_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    content_store: ContentStoreSettings = Field(default_factory=ContentStoreSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.app.environment is not Environment.TEST and not self.auth.principals:
            raise ValueError("at least one authentication principal is required")
        if self.app.environment is Environment.PRODUCTION:
            if self.app.debug:
                raise ValueError("debug must be disabled in production")
            if not self.content_store.root.is_absolute():
                raise ValueError("production ContentStore root must be absolute")
        return self

    def safe_summary(self) -> dict[str, object]:
        """Return bounded startup facts without credentials or connection strings."""

        return {
            "service_name": self.app.service_name,
            "environment": self.app.environment.value,
            "principal_ids": [principal.principal_id for principal in self.auth.principals],
            "principal_count": len(self.auth.principals),
            "log_format": self.observability.log_format,
            "tracing_enabled": self.observability.tracing_enabled,
        }
