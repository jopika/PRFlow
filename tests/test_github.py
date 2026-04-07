"""Tests for github.py — GitHub CLI wrapper."""

import json

import pytest

from prflow.github import get_existing_pr_details
from tests.conftest import completed as _completed


class TestGetExistingPrDetails:
    def test_returns_pr_with_body_and_title(self, mocker):
        pr_data = [{"number": 42, "url": "https://github.com/o/r/pull/42",
                     "state": "OPEN", "title": "Add feature", "body": "## Overview\nDetails"}]
        mocker.patch("prflow.github.subprocess.run",
                     return_value=_completed(json.dumps(pr_data)))

        result = get_existing_pr_details("feature/foo")
        assert result is not None
        assert result["number"] == 42
        assert result["title"] == "Add feature"
        assert result["body"] == "## Overview\nDetails"

    def test_returns_none_when_no_pr(self, mocker):
        mocker.patch("prflow.github.subprocess.run",
                     return_value=_completed("[]"))

        assert get_existing_pr_details("feature/no-pr") is None

    def test_returns_none_on_error(self, mocker):
        mocker.patch("prflow.github.subprocess.run",
                     return_value=_completed(returncode=1, stderr="error"))

        assert get_existing_pr_details("feature/error") is None

    def test_fetches_body_and_title_fields(self, mocker):
        """Verify the gh command includes body and title in --json fields."""
        mock_run = mocker.patch("prflow.github.subprocess.run",
                                return_value=_completed("[]"))

        get_existing_pr_details("feature/check")

        cmd = mock_run.call_args[0][0]
        # Find the --json argument
        json_idx = cmd.index("--json")
        json_fields = cmd[json_idx + 1]
        assert "body" in json_fields
        assert "title" in json_fields
