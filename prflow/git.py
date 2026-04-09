"""Git operations: branch checks, rebase, push, diff."""

from __future__ import annotations

import re
import subprocess

import click


class GitError(Exception):
    """Raised when a git operation fails."""


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitError(f"Command failed: {' '.join(args)}\n{result.stderr.strip()}")
    return result


def current_branch() -> str:
    """Get the current branch name."""
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return result.stdout.strip()


def is_protected_branch(branch: str, protected: list[str]) -> bool:
    """Check if the branch is in the protected list."""
    return branch in protected


def prompt_create_branch() -> str:
    """Interactively ask for a new branch name and check it out."""
    name = click.prompt("Enter new branch name")
    _run(["git", "checkout", "-b", name])
    return name


def get_base_branch(config: dict) -> str:
    """Get base branch from config, or auto-detect via gh repo view."""
    if config.get("base_branch"):
        return config["base_branch"]

    result = subprocess.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise GitError(
            "Could not detect base branch. Set 'base_branch' in config or ensure 'gh' is authenticated."
        )
    return result.stdout.strip()


def fetch_and_rebase(base: str) -> None:
    """Fetch origin and rebase onto origin/<base>."""
    _run(["git", "fetch", "origin"])
    result = subprocess.run(
        ["git", "rebase", f"origin/{base}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Abort the failed rebase so we don't leave the repo in a bad state
        subprocess.run(["git", "rebase", "--abort"], capture_output=True)
        raise GitError(f"Rebase onto origin/{base} failed. Resolve conflicts manually.\n{result.stderr.strip()}")


def get_commits_since_base(base: str) -> list[tuple[str, str]]:
    """Get commits since divergence from base as (hash, message) tuples."""
    result = _run(["git", "log", "--oneline", f"origin/{base}..HEAD"])
    commits = []
    for line in result.stdout.strip().splitlines():
        if line:
            parts = line.split(" ", 1)
            commits.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return commits


def push_branch(branch: str) -> None:
    """Push the branch to origin with --set-upstream."""
    _run(["git", "push", "--set-upstream", "origin", branch])


def get_dirty_files() -> dict[str, list[str]]:
    """Get dirty files categorized by status.

    Returns dict with keys: staged, unstaged, untracked.
    """
    result = _run(["git", "status", "--porcelain"], check=False)
    staged = []
    unstaged = []
    untracked = []

    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        index_status = line[0]
        worktree_status = line[1]
        filepath = line[3:]

        if index_status == "?":
            untracked.append(filepath)
        else:
            if index_status not in (" ", "?"):
                staged.append(filepath)
            if worktree_status not in (" ", "?"):
                unstaged.append(filepath)

    return {"staged": staged, "unstaged": unstaged, "untracked": untracked}


def stage_files(files: list[str]) -> None:
    """Stage the given files via git add."""
    if not files:
        return
    _run(["git", "add", "--"] + files)


def get_diff_for_staged_files(files: list[str]) -> str:
    """Return unified diff of staged changes for the given files (git diff --cached)."""
    if not files:
        return ""
    result = _run(["git", "diff", "--cached", "--"] + files)
    return result.stdout


def commit(message: str, files: list[str] | None = None) -> None:
    """Run git commit with the given message.

    If files is provided, commits only staged changes for those paths — other
    staged files remain staged. Raises GitError on failure.
    """
    cmd = ["git", "commit", "-m", message]
    if files:
        cmd += ["--"] + files
    _run(cmd)


def get_changed_files(base: str) -> list[str]:
    """List files changed in committed work vs origin/<base> (branch commits only)."""
    result = _run(["git", "diff", "--name-only", f"origin/{base}..HEAD"])
    return [f for f in result.stdout.strip().splitlines() if f]


def get_diff_stat(base: str) -> str:
    """Get diff stat of committed changes vs origin/<base>."""
    result = _run(["git", "diff", "--stat", f"origin/{base}..HEAD"])
    return result.stdout.strip()


def get_full_diff(base: str) -> dict[str, str]:
    """Get full diff of committed changes split into per-file chunks.

    Only includes committed code — excludes unstaged/uncommitted changes.
    Returns dict mapping filepath to its diff text.
    """
    result = _run(["git", "diff", f"origin/{base}..HEAD"])
    return _parse_diff_into_files(result.stdout)


def _parse_diff_into_files(diff_text: str) -> dict[str, str]:
    """Split a unified diff into per-file chunks."""
    files = {}
    current_file = None
    current_lines = []

    for line in diff_text.splitlines(keepends=True):
        match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if match:
            if current_file is not None:
                files[current_file] = "".join(current_lines)
            current_file = match.group(2)
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_file is not None:
        files[current_file] = "".join(current_lines)

    return files
