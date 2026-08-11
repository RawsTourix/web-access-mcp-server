import tomllib
from pathlib import Path

from web_access import __version__


def test_package_imports() -> None:
    assert __version__ == "0.2.0"
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__
