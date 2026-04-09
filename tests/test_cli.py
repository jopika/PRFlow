"""Tests for cli.py — Click CLI integration tests."""

from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version as package_version

import click
import pytest

from click.testing import CliRunner

from prflow import __version__
from prflow.cli import _do_commit_flow, _handle_dirty_files, display_body_diff, main
from prflow.git import GitError
from prflow.llm import LLMError
from prflow.picker import PickerFile, PickerResult


class TestCli:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_matches_installed_metadata(self):
        try:
            installed_version = package_version("prflow")
        except PackageNotFoundError:
            pytest.skip("prflow is not installed in the current environment")
        assert installed_version == __version__

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--no-pre-commit" in result.output
        assert "--no-rebase" in result.output
        assert "--dry-run" in result.output
        assert "--full-diff" in result.output
        assert "--yes" in result.output
        assert "--draft" in result.output
        assert "--base" in result.output
        assert "--update" in result.output

    def test_exits_on_git_error(self, mocker):
        """Any GitError during startup should print an error and exit 1."""
        mocker.patch("prflow.cli.load_config", return_value={
            "draft": True, "pre_commit": False, "protected_branches": ["main"],
        })
        mocker.patch("prflow.cli.update.handle_startup_update")
        mocker.patch("prflow.git.current_branch", side_effect=__import__("prflow.git", fromlist=["GitError"]).GitError("not a git repo"))
        runner = CliRunner()
        result = runner.invoke(main, ["--dry-run"])
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_update_flag_handles_update_and_exits(self, mocker):
        mocker.patch("prflow.cli.load_config", return_value={"updates": {"enabled": True}})
        mock_handle = mocker.patch("prflow.cli.update.handle_manual_update")
        mock_current_branch = mocker.patch("prflow.cli.git.current_branch")

        result = CliRunner().invoke(main, ["--update"])

        assert result.exit_code == 0
        mock_handle.assert_called_once_with({"updates": {"enabled": True}})
        mock_current_branch.assert_not_called()

    def test_startup_update_runs_before_main_flow(self, mocker):
        config = {
            "draft": True,
            "pre_commit": False,
            "protected_branches": ["main"],
            "updates": {"enabled": True},
        }
        mocker.patch("prflow.cli.load_config", return_value=config)
        mock_startup = mocker.patch("prflow.cli.update.handle_startup_update")
        mocker.patch("prflow.cli.git.current_branch", side_effect=GitError("not a git repo"))

        CliRunner().invoke(main, ["--dry-run"])

        mock_startup.assert_called_once_with(config, True)


class TestHandleDirtyFiles:
    _config = {"llm": {}}

    def test_no_op_when_clean(self, mocker):
        mock_console = mocker.patch("prflow.cli.console")
        _handle_dirty_files({"staged": [], "unstaged": [], "untracked": []}, True, self._config)
        mock_console.print.assert_not_called()

    def test_staged_table_shown(self, mocker):
        from rich.table import Table
        mock_console = mocker.patch("prflow.cli.console")
        mocker.patch("click.prompt", return_value="y")
        _handle_dirty_files({"staged": ["a.py"], "unstaged": [], "untracked": []}, True, self._config)
        printed_args = [call[0][0] for call in mock_console.print.call_args_list]
        assert any(isinstance(a, Table) and a.title == "Staged files" for a in printed_args)

    def test_all_three_categories_shown(self, mocker):
        from rich.table import Table
        mock_console = mocker.patch("prflow.cli.console")
        mocker.patch("click.prompt", return_value="y")
        _handle_dirty_files(
            {"staged": ["a.py"], "unstaged": ["b.py"], "untracked": ["c.py"]},
            True, self._config,
        )
        printed_args = [call[0][0] for call in mock_console.print.call_args_list]
        titles = {a.title for a in printed_args if isinstance(a, Table)}
        assert "Staged files" in titles
        assert "Unstaged changes" in titles
        assert "Untracked files" in titles

    def test_non_interactive_returns_without_prompt(self, mocker):
        mocker.patch("prflow.cli.console")
        mock_prompt = mocker.patch("click.prompt")
        _handle_dirty_files({"staged": ["a.py"], "unstaged": [], "untracked": []}, False, self._config)
        mock_prompt.assert_not_called()

    def test_y_choice_continues(self, mocker):
        mocker.patch("prflow.cli.console")
        mocker.patch("click.prompt", return_value="y")
        # Should not raise
        _handle_dirty_files({"staged": ["a.py"], "unstaged": [], "untracked": []}, True, self._config)

    def test_n_choice_aborts(self, mocker):
        mocker.patch("prflow.cli.console")
        mocker.patch("click.prompt", return_value="n")
        with pytest.raises(click.Abort):
            _handle_dirty_files({"staged": ["a.py"], "unstaged": [], "untracked": []}, True, self._config)

    def test_commit_option_always_present(self, mocker):
        mocker.patch("prflow.cli.console")
        mock_prompt = mocker.patch("click.prompt", return_value="y")
        _handle_dirty_files({"staged": [], "unstaged": ["b.py"], "untracked": []}, True, self._config)
        prompt_text = mock_prompt.call_args[0][0]
        assert "[c]" in prompt_text

    def test_invalid_choice_re_prompts(self, mocker):
        mocker.patch("prflow.cli.console")
        # First call: invalid "x", second call: valid "y"
        mocker.patch("click.prompt", side_effect=["x", "y"])
        _handle_dirty_files({"staged": [], "unstaged": ["b.py"], "untracked": []}, True, self._config)


def _pf(path: str, category: str = "staged") -> PickerFile:
    return PickerFile(path=path, category=category)


def _mock_picker(mocker, result: PickerResult | None):
    """Patch CommitPicker.run() to return the given result."""
    mock_cls = mocker.patch("prflow.cli.CommitPicker")
    mock_cls.return_value.run.return_value = result
    return mock_cls


_DIRTY = {"staged": ["a.py"], "unstaged": ["b.py"], "untracked": []}


class TestDoCommitFlow:
    _config = {"llm": {}}

    def test_picker_abort_prints_cancelled(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, None)
        mock_commit = mocker.patch("prflow.cli.git.commit")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_not_called()

    def test_empty_selection_prints_cancelled(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[], message=None))
        mock_commit = mocker.patch("prflow.cli.git.commit")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_not_called()

    def test_typed_message_commits_directly(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message="Fix bug"))
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("prflow.cli.git.stage_files")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_called_once_with("Fix bug", files=["a.py"])

    def test_typed_message_skips_llm(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message="Fix bug"))
        mock_generate = mocker.patch("prflow.cli.llm.generate_commit_message")
        mocker.patch("prflow.cli.git.commit")
        mocker.patch("prflow.cli.git.stage_files")

        _do_commit_flow(_DIRTY, self._config)

        mock_generate.assert_not_called()

    def test_unstaged_files_staged_before_commit(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(
            selected_files=[_pf("a.py", "staged"), _pf("b.py", "unstaged")],
            message="Fix bug",
        ))
        mock_stage = mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.git.commit")

        _do_commit_flow(_DIRTY, self._config)

        mock_stage.assert_called_once_with(["b.py"])

    def test_staged_files_not_re_staged(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py", "staged")], message="Fix bug"))
        mock_stage = mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.git.commit")

        _do_commit_flow(_DIRTY, self._config)

        mock_stage.assert_not_called()

    def test_blank_message_triggers_llm(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mock_generate = mocker.patch("prflow.cli.llm.generate_commit_message", return_value="Add feature")
        mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", return_value="y")

        _do_commit_flow(_DIRTY, self._config)

        mock_generate.assert_called_once()

    def test_llm_generated_message_accepted(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.llm.generate_commit_message", return_value="Add feature")
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", return_value="y")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_called_once_with("Add feature", files=["a.py"])

    def test_llm_generated_message_edited(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.llm.generate_commit_message", return_value="Draft")
        mock_editor = mocker.patch("prflow.cli.edit_body_in_editor", return_value="Edited")
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", return_value="e")

        _do_commit_flow(_DIRTY, self._config)

        mock_editor.assert_called_once_with("Draft")
        mock_commit.assert_called_once_with("Edited", files=["a.py"])

    def test_llm_generated_message_rejected_falls_back_to_manual(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.llm.generate_commit_message", return_value="Generated")
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", side_effect=["n", "Manual message"])

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_called_once_with("Manual message", files=["a.py"])

    def test_llm_error_falls_back_to_manual(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.llm.generate_commit_message", side_effect=LLMError("timeout"))
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", return_value="Manual message")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_called_once_with("Manual message", files=["a.py"])

    def test_empty_manual_fallback_skips_commit(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(selected_files=[_pf("a.py")], message=None))
        mocker.patch("prflow.cli.git.get_diff_for_staged_files", return_value="diff")
        mocker.patch("prflow.cli.git.stage_files")
        mocker.patch("prflow.cli.llm.generate_commit_message", side_effect=LLMError("timeout"))
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("click.prompt", return_value="")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_not_called()

    def test_commit_called_with_selected_paths(self, mocker):
        mocker.patch("prflow.cli.console")
        _mock_picker(mocker, PickerResult(
            selected_files=[_pf("a.py"), _pf("c.py")],
            message="Fix bug",
        ))
        mock_commit = mocker.patch("prflow.cli.git.commit")
        mocker.patch("prflow.cli.git.stage_files")

        _do_commit_flow(_DIRTY, self._config)

        mock_commit.assert_called_once_with("Fix bug", files=["a.py", "c.py"])


class TestPreCommitGating:
    """Regression tests: pre-commit should be skipped when .pre-commit-config.yaml is absent."""

    _config = {
        "draft": True,
        "pre_commit": True,
        "protected_branches": ["main"],
        "base_branch": "main",
        "llm": {"backend": "claude", "effort": "low"},
        "jira": {"backend": "url_only", "base_url": None},
    }

    def _setup(self, mocker):
        mocker.patch("prflow.cli.load_config", return_value=self._config)
        mocker.patch("prflow.cli.update.handle_startup_update")
        mocker.patch("prflow.cli.git.current_branch", return_value="feature/test")
        mocker.patch("prflow.cli.git.is_protected_branch", return_value=False)
        mocker.patch("prflow.cli.git.get_dirty_files", return_value={"staged": [], "unstaged": [], "untracked": []})
        mocker.patch("prflow.cli.git.get_base_branch", return_value="main")
        mocker.patch("prflow.cli.git.get_changed_files", return_value=["some_file.py"])
        mocker.patch("prflow.cli.git.get_diff_stat", return_value="some_file.py | 5 +++++")
        mocker.patch("prflow.cli.git.fetch_and_rebase")
        mocker.patch("prflow.cli.git.get_commits_since_base", return_value=[("abc123", "Add feature")])
        mocker.patch("prflow.cli.github.get_existing_pr_details", return_value=None)
        mocker.patch("prflow.cli.llm.generate_pr_content", return_value={"title": "T", "body": "B"})
        mocker.patch("prflow.cli.github.push_and_create_or_update", return_value="https://github.com/org/repo/pull/1")
        mocker.patch("prflow.cli._get_template_section", return_value="")
        mocker.patch("prflow.cli.get_repo_root", return_value="/repo")

    def test_skips_pre_commit_when_no_config_file(self, mocker):
        self._setup(mocker)
        mocker.patch("prflow.cli.os.path.isfile", return_value=False)
        mock_run = mocker.patch("prflow.cli.subprocess.run")

        result = CliRunner().invoke(main, ["--yes"])

        assert result.exit_code == 0
        pre_commit_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "pre-commit"]
        assert pre_commit_calls == [], "pre-commit should not run without a config file"
        assert "Skipped" in result.output

    def test_runs_pre_commit_when_config_exists(self, mocker):
        self._setup(mocker)
        mocker.patch("prflow.cli.os.path.isfile", return_value=True)
        mock_run = mocker.patch(
            "prflow.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        )

        result = CliRunner().invoke(main, ["--yes"])

        assert result.exit_code == 0
        pre_commit_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "pre-commit"]
        assert len(pre_commit_calls) == 1


class TestDisplayBodyDiff:
    def test_shows_additions(self, mocker):
        """Verify additions are shown."""
        mock_console = mocker.patch("prflow.cli.console")
        old = "## Overview\nOriginal content"
        new = "## Overview\nOriginal content\nNew line added"

        display_body_diff(old, new)

        # Should have printed at least one green (addition) line
        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("green" in p for p in printed)

    def test_no_changes(self, mocker):
        """When bodies are identical, show 'no changes'."""
        mock_console = mocker.patch("prflow.cli.console")
        body = "## Overview\nSame content"

        display_body_diff(body, body)

        printed = [str(call) for call in mock_console.print.call_args_list]
        assert any("no changes" in p for p in printed)
