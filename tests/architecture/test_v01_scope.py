"""Negative scope gates keep v0.4+ capabilities out of the v0.3 line."""

from __future__ import annotations

import tomllib
from pathlib import Path

SOURCE_ROOT = Path("src/web_access")


def test_no_v04_capability_packages_exist() -> None:
    future_packages = {
        "browser",
        "jobs",
        "ocr",
    }
    present = {
        path.name.lower()
        for path in SOURCE_ROOT.rglob("*")
        if path.is_dir() and "__pycache__" not in path.parts
    }
    assert present.isdisjoint(future_packages)


def test_no_v04_runtime_dependencies_are_declared() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {
        dependency.split("[", 1)[0].split("<", 1)[0].split(">", 1)[0].lower()
        for dependency in project["dependencies"]
    }
    assert declared.isdisjoint(
        {
            "arq",
            "openpyxl",
            "playwright",
            "python-docx",
            "python-pptx",
        }
    )


def test_production_source_has_no_v04_business_vocabulary() -> None:
    forbidden_import_fragments = (
        "import arq",
        "import playwright",
        "from arq",
        "from playwright",
    )
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(fragment in source for fragment in forbidden_import_fragments), path
