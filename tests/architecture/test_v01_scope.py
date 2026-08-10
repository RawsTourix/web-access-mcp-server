"""Negative scope gates keep v0.3+ capabilities out of Search Runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path

SOURCE_ROOT = Path("src/web_access")


def test_no_v03_capability_packages_exist() -> None:
    future_packages = {
        "retrieval",
        "browser",
        "jobs",
        "workers",
        "ocr",
        "parsing",
    }
    present = {
        path.name.lower()
        for path in SOURCE_ROOT.rglob("*")
        if path.is_dir() and "__pycache__" not in path.parts
    }
    assert present.isdisjoint(future_packages)


def test_no_v03_runtime_dependencies_are_declared() -> None:
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
            "pypdf",
            "python-docx",
            "python-pptx",
            "trafilatura",
        }
    )


def test_production_source_has_no_future_business_vocabulary() -> None:
    forbidden_import_fragments = (
        "import arq",
        "import playwright",
        "import trafilatura",
        "from arq",
        "from playwright",
        "from trafilatura",
    )
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(fragment in source for fragment in forbidden_import_fragments), path
