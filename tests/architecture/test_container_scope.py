from pathlib import Path


def test_compose_contains_only_foundation_services_and_one_public_port() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for required in ("  postgres:\n", "  redis:\n", "  migration:\n", "  api:\n"):
        assert required in compose
    for forbidden in (
        "searxng:",
        "job-worker:",
        "browser-worker:",
        "playwright:",
        "minio:",
        "arq:",
    ):
        assert forbidden not in compose.lower()
    assert compose.count("ports:") == 1
    assert "127.0.0.1:${WEB_ACCESS_API_PORT:-8000}:8000" in compose


def test_runtime_image_is_non_root_and_locked() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "pip install" not in dockerfile
    assert "latest" not in dockerfile.lower()
