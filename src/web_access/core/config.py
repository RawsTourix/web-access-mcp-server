"""Central typed configuration owned by the composition root."""

from __future__ import annotations

import json
from enum import StrEnum
from ipaddress import ip_network
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    PostgresDsn,
    RedisDsn,
    Secret,
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

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    environment: Environment = Environment.DEVELOPMENT
    service_name: NonEmptyText = "web-access"
    debug: bool = False
    host: str = "0.0.0.0"  # noqa: S104 -- container listener is an explicit deployment setting.
    port: int = Field(default=8000, ge=1, le=65535)
    mandatory_dependencies: frozenset[Literal["postgres", "redis", "content_store"]] = frozenset(
        {"postgres", "redis", "content_store"}
    )


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

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
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    url: Secret[PostgresDsn] = Secret(
        PostgresDsn("postgresql+asyncpg://web_access:development-only@localhost:5432/web_access")
    )
    pool_size: int = Field(default=5, ge=1, le=100)
    pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    def resolved_url(self) -> PostgresDsn:
        """Reveal the validated DSN only at an infrastructure adapter boundary."""

        return self.url.get_secret_value()


class RedisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    url: Secret[RedisDsn] = Secret(RedisDsn("redis://localhost:6379/0"))
    namespace: NonEmptyText = "web-access:v1"
    socket_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    def resolved_url(self) -> RedisDsn:
        """Reveal the validated DSN only at an infrastructure adapter boundary."""

        return self.url.get_secret_value()


class ContentStoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    root: Path = Path(".content")
    chunk_size: int = Field(default=64 * 1024, ge=4096, le=4 * 1024 * 1024)

    @field_validator("root")
    @classmethod
    def validate_root(cls, root: Path) -> Path:
        if not str(root).strip() or "\x00" in str(root):
            raise ValueError("invalid ContentStore root")
        return root


class ObservabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    log_format: Literal["json", "console"] = "json"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    tracing_enabled: bool = False
    otlp_endpoint: str | None = None


class SecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    request_id_max_length: int = Field(default=128, ge=16, le=512)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class RetrievalSecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    additional_allowed_ports: frozenset[int] = Field(default=frozenset(), max_length=32)
    internal_cidrs: tuple[str, ...] = Field(default=(), max_length=64)
    policy_revision: str = Field(default="retrieval-egress-v1", min_length=8, max_length=128)

    @field_validator("additional_allowed_ports")
    @classmethod
    def validate_ports(cls, ports: frozenset[int]) -> frozenset[int]:
        if any(port < 1 or port > 65535 for port in ports):
            raise ValueError("Retrieval egress ports must be between 1 and 65535")
        return ports

    @field_validator("internal_cidrs")
    @classmethod
    def validate_internal_cidrs(cls, cidrs: tuple[str, ...]) -> tuple[str, ...]:
        try:
            normalized = tuple(str(ip_network(cidr, strict=True)) for cidr in cidrs)
        except ValueError as error:
            raise ValueError("invalid Retrieval internal CIDR") from error
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate Retrieval internal CIDR")
        return normalized


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    operation_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    batch_concurrency: int = Field(default=8, ge=1, le=32)
    max_connections: int = Field(default=32, ge=1, le=256)
    max_connections_per_host: int = Field(default=4, ge=1, le=32)
    max_redirects: int = Field(default=5, ge=0, le=10)
    stream_chunk_size: int = Field(default=64 * 1024, ge=4096, le=1024 * 1024)
    max_wire_bytes: int = Field(default=16 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    max_entity_bytes: int = Field(default=32 * 1024 * 1024, ge=1024, le=512 * 1024 * 1024)
    max_decompression_ratio: float = Field(default=100.0, ge=1, le=1000)
    read_inactivity_seconds: float = Field(default=5.0, gt=0, le=60)
    security: RetrievalSecuritySettings = Field(default_factory=RetrievalSecuritySettings)

    @model_validator(mode="after")
    def validate_body_limits(self) -> Self:
        if self.max_entity_bytes < self.max_wire_bytes:
            raise ValueError("Retrieval entity limit cannot be below wire limit")
        return self


class SearxngSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    enabled: bool = True
    endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
    profile_revision: str = Field(default="searxng-default-v1", min_length=8, max_length=128)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    max_results: int = Field(default=50, ge=1, le=50)


class YandexSearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    enabled: bool = False
    endpoint: AnyHttpUrl = AnyHttpUrl("https://searchapi.api.cloud.yandex.net/v2/web/search")
    folder_id: str | None = Field(default=None, min_length=1, max_length=50)
    api_key: SecretStr | None = None
    search_type: Literal[
        "SEARCH_TYPE_RU",
        "SEARCH_TYPE_TR",
        "SEARCH_TYPE_COM",
        "SEARCH_TYPE_KK",
        "SEARCH_TYPE_BE",
        "SEARCH_TYPE_UZ",
    ] = "SEARCH_TYPE_RU"
    profile_revision: str = Field(default="yandex-search-v2-v1", min_length=8, max_length=128)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    max_results: int = Field(default=50, ge=1, le=50)

    @model_validator(mode="after")
    def validate_enabled_credentials(self) -> Self:
        if self.enabled and (self.folder_id is None or self.api_key is None):
            raise ValueError("enabled Yandex Search requires folder_id and api_key")
        return self


class SearchRegionProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    provider_id: Literal["searxng", "yandex"]
    provider_region: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_provider_region(self) -> Self:
        if self.provider_id == "yandex":
            if not self.provider_region.isdecimal() or self.provider_region.startswith("0"):
                raise ValueError("Yandex provider region must be a positive decimal ID")
        return self


class SearchRegionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    region_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    label: str = Field(min_length=1, max_length=128)
    mappings: tuple[SearchRegionProviderSettings, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_mapping_uniqueness(self) -> Self:
        providers = [mapping.provider_id for mapping in self.mappings]
        if len(providers) != len(set(providers)):
            raise ValueError("duplicate provider mapping for Search region")
        return self


class SearchCacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    mode: Literal["principal", "shared_public", "disabled"] = "principal"
    searxng_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    yandex_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    single_flight_ttl_seconds: int = Field(default=30, ge=2, le=300)
    waiter_poll_seconds: float = Field(default=0.05, gt=0, le=1)


class SearchRateBucketSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    capacity: int = Field(default=20, ge=1, le=10000)
    refill_per_second: float = Field(default=5.0, gt=0, le=10000)


class SearchProviderRateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    principal: SearchRateBucketSettings = Field(default_factory=SearchRateBucketSettings)
    global_: SearchRateBucketSettings = Field(
        default_factory=lambda: SearchRateBucketSettings(capacity=100, refill_per_second=20),
        alias="global",
    )


class SearchRateLimitSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, populate_by_name=True
    )

    mandatory: bool = True
    searxng: SearchProviderRateSettings = Field(default_factory=SearchProviderRateSettings)
    yandex: SearchProviderRateSettings = Field(default_factory=SearchProviderRateSettings)


class SearchProviderConcurrencySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    local_limit: int = Field(default=10, ge=1, le=1000)
    global_limit: int = Field(default=20, ge=1, le=1000)
    lease_seconds: int = Field(default=65, ge=2, le=600)
    admission_timeout_seconds: float = Field(default=2.0, gt=0, le=60)


class SearchConcurrencySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    searxng: SearchProviderConcurrencySettings = Field(
        default_factory=SearchProviderConcurrencySettings
    )
    yandex: SearchProviderConcurrencySettings = Field(
        default_factory=lambda: SearchProviderConcurrencySettings(local_limit=5, global_limit=10)
    )


class SearchRetrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    searxng_max_attempts: int = Field(default=2, ge=1, le=3)
    yandex_max_attempts: int = Field(default=1, ge=1, le=2)
    backoff_seconds: float = Field(default=0.05, ge=0, le=5)
    jitter_ratio: float = Field(default=0.2, ge=0, le=1)


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    default_provider: Literal["searxng", "yandex"] = "searxng"
    provider_order: tuple[Literal["searxng", "yandex"], ...] = ("searxng", "yandex")
    max_batch_size: int = Field(default=32, ge=1, le=32)
    max_query_length: int = Field(default=4096, ge=1, le=4096)
    max_results: int = Field(default=50, ge=1, le=50)
    max_page: int = Field(default=100, ge=1, le=100)
    batch_concurrency: int = Field(default=8, ge=1, le=32)
    operation_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    searxng: SearxngSettings = Field(default_factory=SearxngSettings)
    yandex: YandexSearchSettings = Field(default_factory=YandexSearchSettings)
    cache: SearchCacheSettings = Field(default_factory=SearchCacheSettings)
    rate_limit: SearchRateLimitSettings = Field(default_factory=SearchRateLimitSettings)
    concurrency: SearchConcurrencySettings = Field(default_factory=SearchConcurrencySettings)
    retry: SearchRetrySettings = Field(default_factory=SearchRetrySettings)
    regions: tuple[SearchRegionSettings, ...] = ()

    @model_validator(mode="after")
    def validate_search_graph(self) -> Self:
        if len(self.provider_order) != len(set(self.provider_order)):
            raise ValueError("duplicate Search provider")
        if self.default_provider not in self.provider_order:
            raise ValueError("default Search provider is not configured")
        selected = self.searxng if self.default_provider == "searxng" else self.yandex
        if not selected.enabled:
            raise ValueError("default Search provider is disabled")
        region_ids = [region.region_id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("duplicate Search region ID")
        for provider, concurrency, timeout in (
            ("searxng", self.concurrency.searxng, self.searxng.request_timeout_seconds),
            ("yandex", self.concurrency.yandex, self.yandex.request_timeout_seconds),
        ):
            if concurrency.lease_seconds <= timeout + 1:
                raise ValueError(
                    f"{provider} concurrency lease must exceed provider timeout and safety margin"
                )
        return self

    def provider_revision(self, provider_id: Literal["searxng", "yandex"]) -> str:
        provider = self.searxng if provider_id == "searxng" else self.yandex
        payload = provider.model_dump(mode="json", exclude={"api_key"})
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        import hashlib

        return hashlib.sha256(canonical.encode()).hexdigest()


class Settings(BaseSettings):
    """Single environment-owned settings graph."""

    model_config = SettingsConfigDict(
        env_prefix="WEB_ACCESS_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    content_store: ContentStoreSettings = Field(default_factory=ContentStoreSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.app.environment is not Environment.TEST and not self.auth.principals:
            raise ValueError("at least one authentication principal is required")
        if self.app.environment is Environment.PRODUCTION:
            if self.app.debug:
                raise ValueError("debug must be disabled in production")
            if not self.content_store.root.is_absolute():
                raise ValueError("production ContentStore root must be absolute")
            if "url" not in self.database.model_fields_set:
                raise ValueError("production PostgreSQL URL must be explicitly configured")
            if "url" not in self.redis.model_fields_set:
                raise ValueError("production Redis URL must be explicitly configured")
            if (
                self.search.searxng.enabled
                and "endpoint" not in self.search.searxng.model_fields_set
            ):
                raise ValueError("production SearXNG endpoint must be explicitly configured")
            if self.search.yandex.enabled and self.search.yandex.endpoint.scheme != "https":
                raise ValueError("production Yandex Search endpoint must use TLS")
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
