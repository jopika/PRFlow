"""Tests for config.py — layered config loading."""

from pathlib import Path

from prflow.config import DEFAULTS, _deep_merge, _load_yaml_file, load_config


class TestDeepMerge:
    def test_flat_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_dict_merge(self):
        base = {"llm": {"backend": "claude", "model": None}}
        override = {"llm": {"model": "opus"}}
        result = _deep_merge(base, override)
        assert result == {"llm": {"backend": "claude", "model": "opus"}}

    def test_list_replacement(self):
        base = {"protected_branches": ["main", "master"]}
        override = {"protected_branches": ["main", "master", "staging"]}
        result = _deep_merge(base, override)
        assert result["protected_branches"] == ["main", "master", "staging"]

    def test_does_not_mutate_base(self):
        base = {"llm": {"backend": "claude"}}
        override = {"llm": {"backend": "openai"}}
        _deep_merge(base, override)
        assert base["llm"]["backend"] == "claude"


class TestLoadYamlFile:
    def test_missing_file(self, tmp_path):
        result = _load_yaml_file(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_valid_yaml(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("jira:\n  base_url: https://example.com/browse\n")
        result = _load_yaml_file(f)
        assert result == {"jira": {"base_url": "https://example.com/browse"}}

    def test_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(": : : not valid yaml [[[")
        result = _load_yaml_file(f)
        assert result == {}

    def test_non_dict_yaml(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        result = _load_yaml_file(f)
        assert result == {}


class TestLoadConfig:
    def test_defaults_only(self, mocker):
        mocker.patch("prflow.config.get_repo_root", side_effect=RuntimeError)
        mocker.patch("prflow.config._load_yaml_file", return_value={})
        config = load_config()
        assert config["llm"]["backend"] == "claude"
        assert config["jira"]["base_url"] is None
        assert config["base_branch"] is None
        assert config["draft"] is True

    def test_global_config_merges(self, mocker, tmp_path):
        mocker.patch("prflow.config.get_repo_root", side_effect=RuntimeError)
        mocker.patch("prflow.config.Path.home", return_value=tmp_path)
        global_cfg = tmp_path / ".prflow.yaml"
        global_cfg.write_text("draft: false\njira:\n  base_url: https://example.com\n")
        config = load_config()
        assert config["draft"] is False
        assert config["jira"]["base_url"] == "https://example.com"
        assert config["llm"]["backend"] == "claude"  # preserved from defaults

    def test_repo_config_overrides_global(self, mocker, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        mocker.patch("prflow.config.get_repo_root", return_value=repo_root)
        mocker.patch("prflow.config.Path.home", return_value=tmp_path)

        global_cfg = tmp_path / ".prflow.yaml"
        global_cfg.write_text("base_branch: main\n")
        repo_cfg = repo_root / ".prflow.yaml"
        repo_cfg.write_text("base_branch: develop\n")

        config = load_config()
        assert config["base_branch"] == "develop"

    def test_cli_overrides_all(self, mocker):
        mocker.patch("prflow.config.get_repo_root", side_effect=RuntimeError)
        mocker.patch("prflow.config._load_yaml_file", return_value={})
        config = load_config(cli_overrides={"draft": False, "base_branch": "release"})
        assert config["draft"] is False
        assert config["base_branch"] == "release"
