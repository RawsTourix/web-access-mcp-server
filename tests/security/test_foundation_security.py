"""Repository-level security invariants for the foundation release."""

from pathlib import Path


def test_local_secret_file_is_ignored_and_not_present() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gitignore
    assert not Path(".env").exists()


def test_no_identity_header_or_auth_bypass_exists_in_production_source() -> None:
    forbidden = (
        "x-user-id",
        "x-principal-id",
        "auth_disabled",
        "disable_auth",
        "skip_auth",
        "bypass_auth",
    )
    for path in Path("src/web_access").rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(marker in source for marker in forbidden), path


def test_example_credentials_remain_explicit_placeholders() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "<generated-" in example
    assignments = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert assignments["WEB_ACCESS_AUTH__PRINCIPALS"] == ""
    assert assignments["WEB_ACCESS_CONTENT_CURSOR_SECRET"] == ""
    assert assignments["POSTGRES_PASSWORD"] == ""
