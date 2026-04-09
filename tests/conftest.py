"""Shared test fixtures and utilities."""

import subprocess

import pytest

import prflow.config


def completed(stdout="", stderr="", returncode=0):
    """Build a CompletedProcess for use in subprocess mocks."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture(autouse=True, scope="session")
def force_low_effort():
    """Force effort=low for all tests to avoid accidental high-cost LLM calls."""
    original = prflow.config.DEFAULTS["llm"]["effort"]
    prflow.config.DEFAULTS["llm"]["effort"] = "low"
    yield
    prflow.config.DEFAULTS["llm"]["effort"] = original


@pytest.fixture
def sample_config():
    """A complete config dict for testing."""
    return {
        "llm": {
            "backend": "claude",
            "model": None,
            "effort": "low",
            "command": None,
            "full_diff_group_size": 10,
            "timeout": 120,
        },
        "jira": {
            "backend": "url_only",
            "base_url": "https://mycompany.atlassian.net/browse",
        },
        "base_branch": "main",
        "protected_branches": ["main", "master"],
        "pre_commit": True,
        "draft": True,
        "updates": {
            "enabled": True,
            "check_interval_hours": 24,
            "github_repo": "jopika/PRFlow",
        },
    }


@pytest.fixture
def sample_template():
    """A sample PR template string."""
    return (
        "## Summary\n"
        "Describe your changes here.\n"
        "\n"
        "## Test Plan\n"
        "- [ ] Unit tests\n"
        "- [ ] Manual testing\n"
        "\n"
        "## Jira\n"
        "Link to ticket.\n"
    )
