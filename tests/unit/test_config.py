from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsError

from web_access.core.config import (
    AppSettings,
    AuthSettings,
    ContentStoreSettings,
    DatabaseSettings,
    Environment,
    PrincipalSettings,
    RedisSettings,
    SearchSettings,
    SearxngSettings,
    SecuritySettings,
    Settings,
)


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WEB_ACCESS_APP__ENVIRONMENT",
        "WEB_ACCESS_AUTH__PRINCIPALS",
        "WEB_ACCESS_AUTH__PRINCIPALS_FILE",
        "WEB_ACCESS_SECURITY__CONTENT_CURSOR_HMAC_SECRET",
        "WEB_ACCESS_DATABASE__URL",
        "WEB_ACCESS_REDIS__URL",
        "WEB_ACCESS_CONTENT_STORE__ROOT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_nested_environment_and_secret_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    token = "high-entropy-token-value-123456789"
    monkeypatch.setenv("WEB_ACCESS_APP__ENVIRONMENT", "development")
    monkeypatch.setenv(
        "WEB_ACCESS_AUTH__PRINCIPALS",
        json.dumps([{"principal_id": "agent-a", "tokens": [token], "scopes": ["*"]}]),
    )
    settings = Settings()
    assert settings.app.environment is Environment.DEVELOPMENT
    assert settings.auth.principals[0].tokens[0].get_secret_value() == token
    assert token not in repr(settings)
    assert token not in json.dumps(settings.safe_summary())


def test_all_configuration_secret_representations_are_redacted() -> None:
    db_secret = "db-canary-secret"
    redis_secret = "redis-canary-secret"
    bearer_secret = "bearer-canary-secret"
    settings = Settings(
        app=AppSettings(environment=Environment.TEST),
        auth=AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="canary-agent",
                    tokens=(SecretStr(bearer_secret),),
                    scopes=frozenset({"read"}),
                ),
            )
        ),
        database=DatabaseSettings.model_validate(
            {"url": f"postgresql+asyncpg://user:{db_secret}@localhost/database"}
        ),
        redis=RedisSettings.model_validate(
            {"url": f"redis://default:{redis_secret}@localhost:6379/0"}
        ),
    )
    rendered = (repr(settings), str(settings), repr(settings.database), str(settings.database))
    summary = json.dumps(settings.safe_summary())
    for canary in (db_secret, redis_secret, bearer_secret):
        assert all(canary not in value for value in rendered)
        assert canary not in summary
    assert db_secret in str(settings.database.resolved_url())
    assert redis_secret in str(settings.redis.resolved_url())


def _assert_validation_error_redacts(canary: str, build) -> None:
    with pytest.raises((ValidationError, SettingsError, ValueError)) as captured:
        build()
    assert canary not in str(captured.value)
    assert canary not in repr(captured.value)


def test_secret_bearing_validation_errors_hide_inputs(tmp_path) -> None:
    _assert_validation_error_redacts(
        "bearer-canary",
        lambda: PrincipalSettings.model_validate(
            {
                "principal_id": "agent",
                "tokens": ["bearer-canary"],
                "scopes": ["read"],
            }
        ),
    )
    _assert_validation_error_redacts(
        "bearer-canary-secret",
        lambda: PrincipalSettings.model_validate(
            {
                "principal_id": "agent",
                "tokens": ["bearer-canary-secret", "bearer-canary-secret"],
                "scopes": ["read"],
            }
        ),
    )
    _assert_validation_error_redacts(
        "bearer-canary-secret",
        lambda: AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="first",
                    tokens=(SecretStr("bearer-canary-secret"),),
                    scopes=frozenset({"read"}),
                ),
                PrincipalSettings(
                    principal_id="second",
                    tokens=(SecretStr("bearer-canary-secret"),),
                    scopes=frozenset({"read"}),
                ),
            )
        ),
    )
    _assert_validation_error_redacts(
        "db-canary-secret",
        lambda: DatabaseSettings.model_validate(
            {"url": "http://user:db-canary-secret@localhost/database"}
        ),
    )
    _assert_validation_error_redacts(
        "redis-canary-secret",
        lambda: RedisSettings.model_validate(
            {"url": "http://default:redis-canary-secret@localhost/0"}
        ),
    )
    malformed = tmp_path / "malformed-principals.json"
    malformed.write_text('{"secret":"bearer-canary-secret"', encoding="utf-8")
    _assert_validation_error_redacts(
        "bearer-canary-secret", lambda: AuthSettings(principals_file=malformed)
    )


def test_malformed_principals_environment_error_hides_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("WEB_ACCESS_APP__ENVIRONMENT", "test")
    monkeypatch.setenv("WEB_ACCESS_AUTH__PRINCIPALS", "bearer-canary-secret{")
    _assert_validation_error_redacts("bearer-canary-secret", Settings)


def _production_settings(**overrides) -> Settings:
    values = {
        "app": AppSettings(environment=Environment.PRODUCTION),
        "auth": AuthSettings(
            principals=(
                PrincipalSettings(
                    principal_id="production-agent",
                    tokens=(SecretStr("production-bearer-token-value"),),
                    scopes=frozenset({"*"}),
                ),
            )
        ),
        "content_store": ContentStoreSettings(root=Path.cwd() / "web-access-content"),
        "database": DatabaseSettings.model_validate(
            {"url": "postgresql+asyncpg://user:password@db/service"}
        ),
        "redis": RedisSettings.model_validate({"url": "redis://redis:6379/0"}),
        "security": SecuritySettings(
            content_cursor_hmac_secret=SecretStr("production-cursor-secret-value-32-bytes")
        ),
        "search": SearchSettings(
            searxng=SearxngSettings.model_validate({"endpoint": "http://searxng:8080"})
        ),
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_implicit_database_default() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL URL must be explicitly configured"):
        _production_settings(database=DatabaseSettings())


def test_production_rejects_implicit_redis_default() -> None:
    with pytest.raises(ValidationError, match="Redis URL must be explicitly configured"):
        _production_settings(redis=RedisSettings())


def test_production_requires_dedicated_content_cursor_secret() -> None:
    with pytest.raises(ValidationError, match="cursor HMAC secret"):
        _production_settings(security=SecuritySettings())


def test_principals_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _clear_settings_env(monkeypatch)
    path = tmp_path / "principals.json"
    path.write_text(
        json.dumps([{"principal_id": "agent-a", "tokens": ["a" * 32], "scopes": ["read"]}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEB_ACCESS_AUTH__PRINCIPALS_FILE", str(path))
    assert Settings().auth.principals[0].principal_id == "agent-a"


@pytest.mark.parametrize(
    "principals",
    [
        [
            {"principal_id": "duplicate", "tokens": ["a" * 32], "scopes": ["read"]},
            {"principal_id": "duplicate", "tokens": ["b" * 32], "scopes": ["read"]},
        ],
        [
            {"principal_id": "agent-a", "tokens": ["same" * 8], "scopes": ["read"]},
            {"principal_id": "agent-b", "tokens": ["same" * 8], "scopes": ["read"]},
        ],
    ],
)
def test_rejects_ambiguous_principals(monkeypatch: pytest.MonkeyPatch, principals) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("WEB_ACCESS_AUTH__PRINCIPALS", json.dumps(principals))
    with pytest.raises(ValidationError):
        Settings()


def test_rejects_both_principal_sources(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _clear_settings_env(monkeypatch)
    path = tmp_path / "principals.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("WEB_ACCESS_AUTH__PRINCIPALS_FILE", str(path))
    monkeypatch.setenv(
        "WEB_ACCESS_AUTH__PRINCIPALS",
        f"[{json.dumps({'principal_id': 'agent', 'tokens': ['a' * 32], 'scopes': ['*']})}]",
    )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings()


def test_empty_registry_only_allowed_for_test_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    with pytest.raises(ValidationError, match="at least one"):
        Settings()
    monkeypatch.setenv("WEB_ACCESS_APP__ENVIRONMENT", "test")
    assert Settings().auth.principals == ()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WEB_ACCESS_DATABASE__URL", "http://not-postgres"),
        ("WEB_ACCESS_REDIS__URL", "http://not-redis"),
        ("WEB_ACCESS_CONTENT_STORE__ROOT", "   "),
    ],
)
def test_rejects_malformed_foundation_config(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("WEB_ACCESS_APP__ENVIRONMENT", "test")
    monkeypatch.setenv(name, value)
    with pytest.raises((ValidationError, ValueError)):
        Settings()
