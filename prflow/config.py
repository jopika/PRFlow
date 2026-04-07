"""Layered configuration: built-in defaults <- ~/.prflow.yaml <- repo .prflow.yaml <- CLI overrides."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

DEFAULTS = {
    "llm": {
        "backend": "claude",
        "model": None,
        "effort": "medium",             # low | medium | high | max
        "command": None,
        "full_diff_group_size": 10,
        "timeout": 120,
    },
    "jira": {
        "backend": "url_only",
        "base_url": None,
    },
    "base_branch": None,
    "protected_branches": ["main", "master"],
    "pre_commit": True,
    "draft": True,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Dicts are merged; scalars/lists are replaced."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_file(path: Path) -> dict:
    """Load a YAML file, returning {} if missing or invalid."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def get_repo_root() -> Path:
    """Get the git repo root via git rev-parse."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Not in a git repository")
    return Path(result.stdout.strip())


def load_config(cli_overrides: dict | None = None) -> dict:
    """Merge: DEFAULTS <- ~/.prflow.yaml <- <repo>/.prflow.yaml <- cli_overrides."""
    config = _deep_merge({}, DEFAULTS)

    # Global user config
    global_path = Path.home() / ".prflow.yaml"
    config = _deep_merge(config, _load_yaml_file(global_path))

    # Repo-level config
    try:
        repo_root = get_repo_root()
        repo_path = repo_root / ".prflow.yaml"
        config = _deep_merge(config, _load_yaml_file(repo_path))
    except RuntimeError:
        pass

    # CLI overrides
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)

    return config
