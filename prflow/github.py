"""GitHub CLI (gh) wrapper for PR operations."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

import click

from prflow import git
from prflow.types import ExistingPR


class GitHubError(Exception):
    """Raised when a gh CLI operation fails."""


def _run_gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a gh command and return the result."""
    result = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitHubError(f"gh command failed: gh {' '.join(args)}\n{result.stderr.strip()}")
    return result


def get_existing_pr_details(branch: str) -> ExistingPR | None:
    """Fetch existing PR metadata including body and title. Returns dict or None."""
    result = _run_gh(
        ["pr", "list", "--head", branch,
         "--json", "number,url,state,title,body",
         "--limit", "1"],
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        prs: object = json.loads(result.stdout)
        if not isinstance(prs, list) or not prs or not isinstance(prs[0], dict):
            return None
        return cast(ExistingPR, prs[0])
    except (json.JSONDecodeError, IndexError):
        return None


@contextmanager
def _body_tempfile(body: str) -> Generator[str]:
    """Write body to a temp file and yield its path, cleaning up on exit."""
    fd, path = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        yield path
    finally:
        os.unlink(path)


def create_pr(title: str, body: str, base: str, draft: bool = True) -> str:
    """Create a PR and return its URL. Body written via --body-file."""
    with _body_tempfile(body) as body_file:
        cmd = ["pr", "create", "--title", title, "--body-file", body_file, "--base", base]
        if draft:
            cmd.append("--draft")
        return _run_gh(cmd).stdout.strip()


def update_pr(number: int, title: str, body: str) -> str:
    """Update an existing PR's title and body. Returns the PR URL."""
    with _body_tempfile(body) as body_file:
        result = _run_gh(
            ["pr", "edit", str(number), "--title", title, "--body-file", body_file]
        )
        return result.stdout.strip() or f"PR #{number} updated"


def push_and_create_or_update(
    branch: str,
    title: str,
    body: str,
    base: str,
    draft: bool = True,
    dry_run: bool = False,
    interactive: bool = True,
    existing_pr: ExistingPR | None = None,
) -> str:
    """Orchestrate: push -> create or update PR.

    If existing_pr is provided, updates that PR. Otherwise creates a new one.
    Returns the PR URL or a dry-run message.
    """
    if dry_run:
        if existing_pr:
            return f"[dry-run] Would update PR #{existing_pr['number']}: {existing_pr['url']}"
        return f"[dry-run] Would create {'draft ' if draft else ''}PR: {title}"

    if existing_pr:
        if interactive:
            click.confirm(
                f"Update PR #{existing_pr['number']} ({existing_pr.get('state', 'open')})?",
                default=True,
                abort=True,
            )
        git.push_branch(branch)
        number = existing_pr["number"]
        url = existing_pr["url"]
        if not isinstance(number, int) or not isinstance(url, str):
            raise GitHubError("Existing PR metadata is missing number or URL")
        update_pr(number, title, body)
        return url
    else:
        git.push_branch(branch)
        return create_pr(title, body, base, draft)
