"""Executable dependency rules for the v0.1 architecture."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path("src/web_access")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _layer_imports(layer: str) -> dict[Path, set[str]]:
    return {
        path: _imports(path)
        for path in (SOURCE_ROOT / layer).rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _assert_no_prefixes(layer: str, forbidden: tuple[str, ...]) -> None:
    violations = {
        path: sorted(name for name in imports if name.startswith(forbidden))
        for path, imports in _layer_imports(layer).items()
        if any(name.startswith(forbidden) for name in imports)
    }
    assert not violations


def test_domain_is_independent_of_outer_layers_and_frameworks() -> None:
    _assert_no_prefixes(
        "domain",
        (
            "web_access.application",
            "web_access.transport",
            "web_access.infrastructure",
            "web_access.bootstrap",
            "web_access.entrypoints",
            "fastapi",
            "fastmcp",
            "sqlalchemy",
            "asyncpg",
            "redis",
            "opentelemetry",
            "prometheus_client",
        ),
    )


def test_application_does_not_depend_on_adapters_or_composition() -> None:
    _assert_no_prefixes(
        "application",
        (
            "web_access.transport",
            "web_access.infrastructure",
            "web_access.bootstrap",
            "web_access.entrypoints",
            "fastapi",
            "fastmcp",
            "sqlalchemy",
            "asyncpg",
            "redis",
            "opentelemetry",
            "prometheus_client",
        ),
    )


def test_infrastructure_does_not_depend_on_transports_or_composition() -> None:
    _assert_no_prefixes(
        "infrastructure",
        (
            "web_access.transport",
            "web_access.bootstrap",
            "web_access.entrypoints",
        ),
    )


def test_transports_use_ports_not_concrete_infrastructure_or_bootstrap() -> None:
    _assert_no_prefixes(
        "transport",
        (
            "web_access.infrastructure",
            "web_access.bootstrap",
            "web_access.entrypoints",
        ),
    )


def test_rest_and_mcp_facades_do_not_import_each_other() -> None:
    _assert_no_prefixes("transport/rest", ("web_access.transport.mcp",))
    _assert_no_prefixes("transport/mcp", ("web_access.transport.rest",))
