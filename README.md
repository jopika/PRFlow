# prflow

A CLI tool that automates the full PR preparation flow: branch safety check, rebase, pre-commit hooks, LLM-generated title and description, Jira linking, and idempotent PR creation or update — all in one command.

## Requirements

- Python ≥ 3.9
- [`gh`](https://cli.github.com/) — GitHub CLI, authenticated
- [`claude`](https://claude.ai/code) CLI (default LLM backend)
- `git`
- `pre-commit` (optional, used if present)

## Installation

The primary install path is a single script that downloads the latest GitHub Release and installs it with `pipx`.

### Step 1: Install prerequisites

- Python 3.9 or newer
- [`pipx`](https://pipx.pypa.io/)
- `curl`
- [`gh`](https://cli.github.com/) authenticated with GitHub
- [`claude`](https://claude.ai/code) CLI if you want the default LLM backend

Install `pipx` if you do not already have it:

```bash
brew install pipx   # macOS
pip install pipx    # other platforms
```

### Step 2: Run the installer

```bash
curl -fsSL https://raw.githubusercontent.com/jopika/PRFlow/main/install.sh | bash
```

The installer downloads the latest release wheel, installs `prflow` with `pipx`, and then walks you through setting up `~/.prflow.yaml`:

```
Setting up ~/.prflow.yaml
Press Enter to accept the default shown in [brackets].

Jira base URL (e.g. https://your-company.atlassian.net/browse):
LLM effort level (low/medium/high/max) [medium]:
Claude model override (leave blank for CLI default):
Create PRs as drafts by default? [Y/n]:
Enable automatic update checks? [Y/n]:
Protected branches (comma-separated) [main,master]:
```

### Step 3: Verify the install

```bash
prflow --version
```

Re-run the same installer command at any time to upgrade or reconfigure. To uninstall:

```bash
pipx uninstall prflow
```

### Alternative: install from a local checkout

If you are developing on `prflow` itself, clone the repo and run the same installer locally:

```bash
git clone git@github.com:jopika/PRFlow.git
cd PRFlow
./install.sh
```

### Development install

For local development with an editable install:

```bash
pip install -e ".[dev]"
```

## Usage

```
$ prflow [OPTIONS]
```

Run from any branch in any GitHub-backed git repo.

### Options

| Flag | Description |
|---|---|
| `--no-pre-commit` | Skip pre-commit hooks |
| `--no-rebase` | Skip fetch and rebase |
| `--draft / --no-draft` | Override draft setting from config |
| `--base BRANCH` | Override base branch |
| `--dry-run` | Print what would happen without executing |
| `--update` | Check for a newer `prflow` release and optionally upgrade |
| `--yes`, `-y` | Non-interactive: accept all defaults, skip prompts |
| `--full-diff` | Use full diff with multi-agent analysis (slower, more thorough) |
| `--seed TEXT`, `-s TEXT` | Extra context to seed the LLM (intent, background, notes) |
| `--version` | Show version |

## Interactive Flow

### Creating a new PR

```
$ prflow

[Branch] Current: feature/add-auth ✓

[Dirty files] Uncommitted changes detected:
  Staged:    src/auth.py
  Continue anyway? [Y/n]:

[Pre-commit] Running pre-commit on 3 changed file(s)... ✓
[Sync] Fetching + rebasing onto origin/main... ✓

[Commits] 2 commit(s) included:
  a1b2c3d  Add JWT authentication middleware
  d4e5f6a  Add auth configuration endpoint

[Context] Additional context for the LLM (press Enter to skip):
> This PR introduces JWT auth as part of the security hardening initiative

[Jira] Ticket key (blank to skip): PROJ-456
  → https://mycompany.atlassian.net/browse/PROJ-456

[LLM] Generating PR content with Claude... ✓

  Title: Add JWT authentication middleware with config endpoint

  ── Body preview ───────────────────────────────────────────
  ## Overview
  Adds JWT-based authentication...
  ───────────────────────────────────────────────────────────

  Edit body in $EDITOR? [y/N]:

[PR] Pushing to origin/feature/add-auth... ✓
[PR] Creating draft PR... ✓
  → https://github.com/myorg/myrepo/pull/142
```

### Updating an existing PR

When a PR already exists for the current branch, `prflow` fetches the existing body, sends it to the LLM alongside the full commit history, and shows a colored diff of what changed before applying.

```
$ prflow --no-rebase

[Branch] Current: feature/add-auth ✓
[Commits] 4 commit(s) included:
  ...
  e7f8a9b  Add token refresh logic
  b0c1d2e  Fix token expiry edge case

[PR] Existing PR found: #142 (open)
[LLM] Updating PR content based on existing body... ✓

  Title: Add JWT authentication middleware with config endpoint (unchanged)

  ── Changes to PR body ─────────────────────────────────────
    ## Overview
    Adds JWT-based authentication...
  + Includes token refresh logic and edge case handling for expiry.

    ## Changes
    - Added auth.py with JWT validation
  + - Added token refresh with configurable TTL
  + - Fixed edge case where expired tokens weren't rejected
  ───────────────────────────────────────────────────────────

  Edit body in $EDITOR? [y/N]:

[PR] Pushing to origin/feature/add-auth... ✓
[PR] Updated: https://github.com/myorg/myrepo/pull/142
```

The LLM preserves your existing body (including manual edits made on GitHub) and adds information about new commits. It won't remove content you added manually.

### `--full-diff` mode

By default, `prflow` sends only the diff stat to the LLM (fast, low token cost). With `--full-diff`, it runs a multi-agent pipeline:

1. The full diff is split into chunks of up to 10 files, grouped by directory
2. Sub-agents analyze each chunk in parallel (up to 4 concurrent)
3. An orchestrator synthesizes all summaries into the final PR description

Use this for large or complex PRs where the stat summary isn't enough context.

## Configuration

`prflow` uses layered YAML config. Later layers override earlier ones:

| Layer | Path | Purpose |
|---|---|---|
| Built-in defaults | (hardcoded) | Sensible starting point |
| Global user config | `~/.prflow.yaml` | Your cross-repo preferences |
| Repo config | `.prflow.yaml` (repo root) | Repo-specific overrides |
| CLI flags | `--base`, `--draft`, etc. | Per-invocation overrides |

### Example `~/.prflow.yaml`

```yaml
jira:
  base_url: https://your-company.atlassian.net/browse

protected_branches: [main, master, staging]

draft: true

llm:
  effort: high
```

### Example `.prflow.yaml` (repo-level)

```yaml
base_branch: develop

llm:
  model: claude-opus-4-6
  effort: medium
  timeout: 180
```

### Update checks

`prflow` can check GitHub Releases for a newer version of itself.

- Automatic checks are throttled to once every 24 hours by default.
- If a newer version is found, `prflow` prompts once interactively.
- If you decline, later runs show a small startup banner instead of prompting again.
- Run `prflow --update` at any time to check manually and optionally upgrade.
- The upgrade command is `pipx upgrade prflow`.

To disable automatic checks:

```yaml
updates:
  enabled: false
```

### All config keys

| Key | Default | Description |
|---|---|---|
| `base_branch` | `null` | Base branch for PRs. Auto-detected via `gh repo view` if not set. |
| `protected_branches` | `[main, master]` | Branches you cannot open a PR from. |
| `pre_commit` | `true` | Run pre-commit hooks on changed files before pushing. |
| `draft` | `true` | Create PRs as drafts by default. |
| `updates.enabled` | `true` | Enable automatic update checks and startup banners. |
| `updates.check_interval_hours` | `24` | How often `prflow` checks GitHub Releases for a newer version. |
| `updates.github_repo` | `jopika/PRFlow` | GitHub repo used as the release source for update checks. |
| `llm.backend` | `claude` | LLM backend: `claude`, `openai` (stub), or `custom`. |
| `llm.model` | `null` | Override the Claude model. Uses the CLI default if not set. |
| `llm.effort` | `medium` | Claude thinking effort: `low`, `medium`, `high`, or `max`. |
| `llm.command` | `null` | Shell command for the `custom` backend. Prompt is passed via stdin. |
| `llm.full_diff_group_size` | `10` | Max files per chunk in `--full-diff` mode. |
| `llm.timeout` | `120` | LLM call timeout in seconds. |
| `jira.backend` | `url_only` | Jira backend: `url_only`, `rest_api` (stub), or `mcp` (stub). |
| `jira.base_url` | `null` | Jira instance URL. Jira prompts are skipped if not set. |

### Jira backends

| Backend | Status | Description |
|---|---|---|
| `url_only` | Ready | Constructs a link from the ticket key. Requires `jira.base_url`. |
| `rest_api` | Stub | Fetches ticket title/description via Jira REST API. Needs `jira.token` and `jira.email`. |
| `mcp` | Stub | Intended for use inside Claude Code with a Jira MCP server configured. |

## PR body structure

When no repo PR template is found, `prflow` uses this default structure:

```markdown
## Overview
[High-level description of what is changing and why]

## Changes
[Detailed breakdown of the changes introduced]

## Artifacts
[Jira links, references to documentation, or other relevant links]
```

If a `.github/pull_request_template.md` (or similar) exists in the repo, its sections are used instead.

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests mock all subprocess calls — no real git, gh, or claude invocations during the test suite.

## Releases

Releases are managed by GitHub Actions with Release Please.

### Commit message format

Release Please only opens release PRs for releasable commits it can parse. In practice, that means merge commits and direct commits to `main` should use Conventional Commits:

- `feat: add interactive commit picker`
- `fix: preserve staged files when commit is cancelled`
- `deps: update click to 8.1.8`

### Release cycle

1. Merge normal feature and fix PRs into `main`.
2. Every push to `main` runs the Release Please workflow.
3. If there are unreleased changes, Release Please opens or updates a dedicated release PR.
4. That release PR carries the proposed version bump and changelog updates.
5. Review the release PR like any other change. Edit the changelog text if the generated summary needs cleanup.
6. Merge the release PR when you are ready to publish.
7. Merging the release PR creates the Git tag, publishes the GitHub Release, builds the package artifacts, and uploads them to the release page.

### What Release Please updates

- `pyproject.toml` for the package version
- `CHANGELOG.md` for release notes
- `.release-please-manifest.json` to track the latest released version

The CLI version shown by `prflow --version` reads from installed package metadata and falls back to `pyproject.toml` in a local checkout, so the release version stays aligned with the packaged build.

### Release artifacts

When a release is created, GitHub Actions builds and attaches:

- `prflow-<version>.tar.gz`
- `prflow-<version>.zip`
- `prflow-<version>-py3-none-any.whl`

The workflow validates the built Python package metadata with `twine check` before uploading the assets.

### Day-to-day maintainer flow

- Merge regular work into `main`.
- Wait for Release Please to open or refresh the release PR.
- Review the proposed version and `CHANGELOG.md`.
- Edit the changelog in the release PR if you want cleaner notes.
- Merge the release PR to publish the release.

### Notes

- You only need to create a release tag by hand once, during the initial bootstrap.
- After bootstrap, do not create release tags by hand; Release Please will create them when the release PR is merged.
- If Release Please logs `commit could not be parsed`, check that the merged commit titles follow Conventional Commits.
- You do not need to manually edit the version in multiple files.
- CI in `.github/workflows/ci.yml` verifies tests and packaging on pull requests and on pushes to `main`.
