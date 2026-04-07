"""Tests for cli.py — Click CLI integration tests."""

from io import StringIO

from click.testing import CliRunner
from rich.console import Console

from prflow import __version__
from prflow.cli import display_body_diff, main


class TestCli:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

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

    def test_exits_on_git_error(self, mocker):
        """Any GitError during startup should print an error and exit 1."""
        mocker.patch("prflow.cli.load_config", return_value={
            "draft": True, "pre_commit": False, "protected_branches": ["main"],
        })
        mocker.patch("prflow.git.current_branch", side_effect=__import__("prflow.git", fromlist=["GitError"]).GitError("not a git repo"))
        runner = CliRunner()
        result = runner.invoke(main, ["--dry-run"])
        assert result.exit_code != 0
        assert "Error" in result.output


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
