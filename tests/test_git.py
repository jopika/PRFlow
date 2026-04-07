"""Tests for git.py — git operations."""

import pytest

from prflow.git import (
    GitError,
    _parse_diff_into_files,
    current_branch,
    get_base_branch,
    get_changed_files,
    get_commits_since_base,
    get_dirty_files,
    get_diff_stat,
    fetch_and_rebase,
    is_protected_branch,
    push_branch,
)
from tests.conftest import completed as _completed


class TestCurrentBranch:
    def test_parses_output(self, mocker):
        mocker.patch("prflow.git.subprocess.run", return_value=_completed("feature/foo\n"))
        assert current_branch() == "feature/foo"


class TestIsProtectedBranch:
    def test_protected(self):
        assert is_protected_branch("main", ["main", "master"]) is True

    def test_not_protected(self):
        assert is_protected_branch("feature/bar", ["main", "master"]) is False

    def test_custom_list(self):
        assert is_protected_branch("staging", ["main", "master", "staging"]) is True


class TestGetBaseBranch:
    def test_from_config(self, mocker):
        result = get_base_branch({"base_branch": "develop"})
        assert result == "develop"

    def test_auto_detect(self, mocker):
        mocker.patch("prflow.git.subprocess.run", return_value=_completed("main\n"))
        result = get_base_branch({"base_branch": None})
        assert result == "main"

    def test_auto_detect_failure(self, mocker):
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(returncode=1, stderr="error"))
        with pytest.raises(GitError, match="Could not detect base branch"):
            get_base_branch({"base_branch": None})


class TestFetchAndRebase:
    def test_success(self, mocker):
        mock_run = mocker.patch("prflow.git.subprocess.run", return_value=_completed())
        fetch_and_rebase("main")
        calls = mock_run.call_args_list
        assert calls[0][0][0] == ["git", "fetch", "origin"]
        assert calls[1][0][0] == ["git", "rebase", "origin/main"]

    def test_conflict_aborts_and_raises(self, mocker):
        mock_run = mocker.patch("prflow.git.subprocess.run")
        # fetch succeeds, rebase fails, abort succeeds
        mock_run.side_effect = [
            _completed(),  # fetch
            _completed(returncode=1, stderr="CONFLICT"),  # rebase
            _completed(),  # rebase --abort
        ]
        with pytest.raises(GitError, match="Rebase onto origin/main failed"):
            fetch_and_rebase("main")


class TestGetCommitsSinceBase:
    def test_parses_log(self, mocker):
        log_output = "a1b2c3d Add auth\nd4e5f6a Fix config\n"
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(log_output))
        commits = get_commits_since_base("main")
        assert commits == [("a1b2c3d", "Add auth"), ("d4e5f6a", "Fix config")]

    def test_empty_log(self, mocker):
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(""))
        assert get_commits_since_base("main") == []


class TestPushBranch:
    def test_calls_push(self, mocker):
        mock_run = mocker.patch("prflow.git.subprocess.run", return_value=_completed())
        push_branch("feature/foo")
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["git", "push", "--set-upstream", "origin", "feature/foo"]


class TestGetDirtyFiles:
    def test_clean(self, mocker):
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(""))
        result = get_dirty_files()
        assert result == {"staged": [], "unstaged": [], "untracked": []}

    def test_mixed(self, mocker):
        porcelain = "M  staged.py\n M unstaged.py\n?? new_file.py\nMM both.py\n"
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(porcelain))
        result = get_dirty_files()
        assert "staged.py" in result["staged"]
        assert "unstaged.py" in result["unstaged"]
        assert "new_file.py" in result["untracked"]
        assert "both.py" in result["staged"]
        assert "both.py" in result["unstaged"]


class TestGetDiffStat:
    def test_returns_stat(self, mocker):
        stat = " file.py | 10 ++++------\n 1 file changed"
        mocker.patch("prflow.git.subprocess.run", return_value=_completed(stat))
        assert get_diff_stat("main") == stat.strip()


class TestGetChangedFiles:
    def test_returns_list(self, mocker):
        mocker.patch("prflow.git.subprocess.run",
                     return_value=_completed("src/auth.py\ntests/test_auth.py\n"))
        result = get_changed_files("main")
        assert result == ["src/auth.py", "tests/test_auth.py"]

    def test_empty_when_no_changes(self, mocker):
        mocker.patch("prflow.git.subprocess.run",
                     return_value=_completed(""))
        assert get_changed_files("main") == []

    def test_filters_blank_lines(self, mocker):
        mocker.patch("prflow.git.subprocess.run",
                     return_value=_completed("foo.py\n\nbar.py\n"))
        assert get_changed_files("main") == ["foo.py", "bar.py"]


class TestParseDiffIntoFiles:
    def test_splits_files(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+new line\n"
            "diff --git a/bar.py b/bar.py\n"
            "--- a/bar.py\n"
            "+++ b/bar.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = _parse_diff_into_files(diff)
        assert set(result.keys()) == {"foo.py", "bar.py"}
        assert "+new line" in result["foo.py"]
        assert "-old" in result["bar.py"]

    def test_empty_diff(self):
        assert _parse_diff_into_files("") == {}

    def test_single_file(self):
        diff = "diff --git a/only.py b/only.py\n+content\n"
        result = _parse_diff_into_files(diff)
        assert "only.py" in result
