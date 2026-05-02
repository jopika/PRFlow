from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import cast


def _read_version_from_pyproject() -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # pyright: ignore[reportMissingImports]

    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text())
    project = cast(dict[str, object], data["project"])
    return cast(str, project["version"])


try:
    __version__ = package_version("prflow")
except PackageNotFoundError:
    __version__ = _read_version_from_pyproject()
