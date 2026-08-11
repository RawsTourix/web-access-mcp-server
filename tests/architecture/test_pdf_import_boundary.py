from __future__ import annotations

import ast
from pathlib import Path


def test_pypdf_is_imported_only_by_the_private_worker() -> None:
    source_root = Path("src/web_access")
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name if node.names else None
            if module == "pypdf" or (module is not None and module.startswith("pypdf.")):
                if path.as_posix() != "src/web_access/workers/pdf_parser.py":
                    offenders.append(path.as_posix())
    assert offenders == []
