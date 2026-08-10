from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from web_access.core.config import Environment, Settings


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WEB_ACCESS_APP__ENVIRONMENT",
        "WEB_ACCESS_AUTH__PRINCIPALS",
        "WEB_ACCESS_AUTH__PRINCIPALS_FILE",
        "WEB_ACCESS_DATABASE__URL",
        "WEB_ACCESS_REDIS__URL",
        "WEB_ACCESS_CONTENT_STORE__ROOT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_nested_environment_and_secret_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    token = "high-entropy-token-value"
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


def test_principals_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _clear_settings_env(monkeypatch)
    path = tmp_path / "principals.json"
    path.write_text(
        json.dumps([{"principal_id": "agent-a", "tokens": ["token-a"], "scopes": ["read"]}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEB_ACCESS_AUTH__PRINCIPALS_FILE", str(path))
    assert Settings().auth.principals[0].principal_id == "agent-a"


@pytest.mark.parametrize(
    "principals",
    [
        [
            {"principal_id": "duplicate", "tokens": ["token-a"], "scopes": ["read"]},
            {"principal_id": "duplicate", "tokens": ["token-b"], "scopes": ["read"]},
        ],
        [
            {"principal_id": "agent-a", "tokens": ["same"], "scopes": ["read"]},
            {"principal_id": "agent-b", "tokens": ["same"], "scopes": ["read"]},
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
        '[{"principal_id":"agent","tokens":["token"],"scopes":["*"]}]',
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
