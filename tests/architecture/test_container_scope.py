from pathlib import Path


def test_compose_contains_v03_control_plane_and_one_public_port() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for required in (
        "  postgres:\n",
        "  redis:\n",
        "  searxng:\n",
        "  migration:\n",
        "  api:\n",
    ):
        assert required in compose
    for forbidden in (
        "job-worker:",
        "browser-worker:",
        "playwright:",
        "minio:",
        "arq:",
    ):
        assert forbidden not in compose.lower()
    assert compose.count("ports:") == 1
    assert "127.0.0.1:${WEB_ACCESS_API_PORT:-8000}:8000" in compose
    assert "searxng/searxng:2026.7.28-c01178d03@sha256:" in compose
    assert compose.count("image: web-access-mcp-server:0.3") == 2
    assert "image: web-access-mcp-server:0.2" not in compose
    assert "image: web-access-mcp-server:0.1" not in compose
    searxng_service = compose.split("  searxng:\n", 1)[1].split("\n  migration:", 1)[0]
    assert "ports:" not in searxng_service
    assert "settings.yml:/etc/searxng/settings.yml:ro" in searxng_service


def test_runtime_image_is_non_root_and_locked() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "pip install" not in dockerfile
    assert "latest" not in dockerfile.lower()


def test_parser_isolation_uses_explicit_least_privilege_container_posture() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8").lower()
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8").lower()
    assert "seccomp=builtin" in compose
    assert "seccomp=unconfined" not in compose
    assert "privileged:" not in compose
    assert "cap_add:" not in compose
    assert "cap_sys_admin" not in compose
    assert "docker.sock" not in compose
    assert "libseccomp2" in dockerfile


def test_searxng_profile_enables_json_without_stored_secrets() -> None:
    profile = Path("deployment/searxng/settings.yml").read_text(encoding="utf-8")
    assert "    - json" in profile
    assert "secret_key:" not in profile
    assert "SEARXNG_SECRET:" not in profile
