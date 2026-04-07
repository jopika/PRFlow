"""CLI entry point — orchestrates the full PR preparation flow."""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
import tempfile

import click
from rich.console import Console
from rich.table import Table

from prflow import __version__, git, github, jira, llm, template
from prflow.config import get_repo_root, load_config

console = Console()


def _print_step(label: str, message: str, style: str = "bold cyan"):
    console.print(f"[{style}][{label}][/{style}] {message}")


def edit_body_in_editor(body: str) -> str:
    """Open body in $EDITOR for editing, return the result."""
    editor = os.environ.get("EDITOR", "vi")
    fd, tmppath = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        result = subprocess.run([editor, tmppath])
        if result.returncode != 0:
            raise click.ClickException(f"Editor exited with code {result.returncode}")
        with open(tmppath) as f:
            return f.read()
    finally:
        os.unlink(tmppath)


def display_body_diff(old_body: str, new_body: str) -> None:
    """Show a unified diff of old vs new PR body with Rich coloring."""
    old_lines = old_body.splitlines()
    new_lines = new_body.splitlines()

    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="current", tofile="updated",
        lineterm="",
    ))

    if not diff_lines:
        console.print("[dim]  (no changes to body)[/dim]")
        return

    console.rule("Changes to PR body")
    for line in diff_lines:
        if line.startswith("+++") or line.startswith("---"):
            continue  # skip file headers
        elif line.startswith("+"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]")
        else:
            console.print(f"[dim]{line}[/dim]")
    console.rule()


def _get_template_section() -> str:
    """Discover the repo's PR template and format it for prompt injection."""
    try:
        repo_root = get_repo_root()
        template_text = template.discover_template(repo_root)
    except RuntimeError:
        return ""
    if not template_text:
        return ""
    sections = template.parse_sections(template_text)
    return template.format_sections_for_prompt(sections)


@click.command()
@click.option("--no-pre-commit", is_flag=True, help="Skip pre-commit hooks")
@click.option("--no-rebase", is_flag=True, help="Skip fetch and rebase")
@click.option("--draft/--no-draft", default=None, help="Create PR as draft (default: from config)")
@click.option("--base", default=None, help="Override base branch")
@click.option("--dry-run", is_flag=True, help="Print actions without executing")
@click.option("--yes", "-y", is_flag=True, help="Non-interactive, accept all defaults")
@click.option("--full-diff", is_flag=True, help="Use full diff with multi-agent analysis")
@click.option("--seed", "-s", default=None, help="Extra context to seed the LLM (intent, background, notes)")
@click.version_option(version=__version__, prog_name="prflow")
def main(no_pre_commit, no_rebase, draft, base, dry_run, yes, full_diff, seed):
    """Automate PR preparation: branch check, rebase, LLM-generated description, and PR creation."""
    try:
        _run(no_pre_commit, no_rebase, draft, base, dry_run, yes, full_diff, seed)
    except (git.GitError, llm.LLMError, github.GitHubError) as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    except click.Abort:
        console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(1)


def _run(no_pre_commit, no_rebase, draft, base, dry_run, yes, full_diff, seed):
    cli_overrides = {}
    if base is not None:
        cli_overrides["base_branch"] = base
    if draft is not None:
        cli_overrides["draft"] = draft

    config = load_config(cli_overrides)
    use_draft = config["draft"]
    interactive = not yes
    seed_section = seed or ""

    # 1. Branch safety check
    branch = git.current_branch()
    protected = config.get("protected_branches", ["main", "master"])

    if git.is_protected_branch(branch, protected):
        console.print(f"[bold red][Branch][/bold red] On protected branch '{branch}'!")
        if interactive:
            branch = git.prompt_create_branch()
            _print_step("Branch", f"Switched to: {branch}")
        else:
            console.print("Cannot create PR from a protected branch. Use a feature branch.")
            sys.exit(1)
    else:
        _print_step("Branch", f"Current: {branch} [green]✓[/green]")

    # 2. Dirty files warning
    dirty = git.get_dirty_files()
    has_dirty = any(dirty.values())
    if has_dirty:
        table = Table(title="Uncommitted changes", show_header=True)
        table.add_column("Category", style="bold")
        table.add_column("Files")
        for category, files in dirty.items():
            if files:
                table.add_row(category.capitalize(), ", ".join(files))
        console.print(table)
        if interactive:
            click.confirm("Continue anyway?", default=True, abort=True)

    # 3. Detect base branch early (needed for pre-commit file scoping and rebase)
    base_branch = git.get_base_branch(config)

    # 4. Pre-commit — run only on PR files, not all files
    if not no_pre_commit and config.get("pre_commit", True):
        changed_files = git.get_changed_files(base_branch)
        if changed_files:
            _print_step("Pre-commit", f"Running pre-commit on {len(changed_files)} changed file(s)...")
            result = subprocess.run(
                ["pre-commit", "run", "--files"] + changed_files,
                capture_output=False,
            )
            if result.returncode != 0:
                console.print("[bold red][Pre-commit][/bold red] Pre-commit hooks failed. Fix issues and retry.")
                sys.exit(1)
            _print_step("Pre-commit", "[green]✓[/green]")
        else:
            _print_step("Pre-commit", "[dim]Skipped — no committed changes yet[/dim]")

    if not no_rebase:
        _print_step("Sync", f"Fetching + rebasing onto origin/{base_branch}...")
        git.fetch_and_rebase(base_branch)
        _print_step("Sync", f"Rebased onto origin/{base_branch} [green]✓[/green]")

    # 5. Collect commits (branch commits only — origin/<base>..HEAD excludes upstream)
    commits = git.get_commits_since_base(base_branch)
    if not commits:
        console.print("[yellow]No commits found since base branch. Nothing to do.[/yellow]")
        sys.exit(0)

    _print_step("Commits", f"{len(commits)} commit(s) included:")
    for h, m in commits:
        console.print(f"  [dim]{h}[/dim]  {m}")

    # Seed prompt (interactive unless --seed was passed or --yes)
    if seed is None and interactive:
        seed = click.prompt(
            "\n[Context] Additional context for the LLM (press Enter to skip)",
            default="",
            show_default=False,
        ) or None
        seed_section = seed or ""

    # 5.5. Check for existing PR
    existing_pr = github.get_existing_pr_details(branch)

    if existing_pr:
        # === UPDATE MODE ===
        _print_step("PR", f"Existing PR found: #{existing_pr['number']} ({existing_pr.get('state', 'open')})")

        existing_title = existing_pr.get("title", "")
        existing_body = existing_pr.get("body", "")

        # Collect diff stat (branch changes only)
        diff_stat = git.get_diff_stat(base_branch)

        pr_content = llm.generate_pr_update(
            config, existing_title, existing_body,
            commits, diff_stat,
            seed_section=seed_section,
        )

        title = pr_content["title"]
        body = pr_content["body"]

        # Show title change
        console.print()
        if title != existing_title:
            console.print(f"  [bold]Title:[/bold] {title}")
            console.print(f"  [dim](was: {existing_title})[/dim]")
        else:
            console.print(f"  [bold]Title:[/bold] {title} [dim](unchanged)[/dim]")
        console.print()

        # Show body diff
        display_body_diff(existing_body, body)

    else:
        # === CREATE MODE ===
        # 6. Jira
        jira_snippet = ""
        if interactive:
            ticket_key = click.prompt("Jira ticket key (blank to skip)", default="", show_default=False)
        else:
            ticket_key = ""

        if ticket_key:
            if jira.is_configured(config):
                backend = jira.get_backend(config)
                ticket_data = backend.get_ticket(ticket_key)
                jira_snippet = jira.format_for_pr(ticket_data)
                _print_step("Jira", f"→ {ticket_data.get('url', ticket_key)}")
            else:
                jira_snippet = f"**Jira:** {ticket_key}"
                _print_step("Jira", f"→ {ticket_key} (no base_url configured — key only)")

        # 7. Discover PR template
        template_section = _get_template_section()

        # 8. Collect diff + generate PR content
        if full_diff:
            file_diffs = git.get_full_diff(base_branch)
            pr_content = llm.generate_pr_content_full_diff(
                config, commits, file_diffs,
                jira_snippet=jira_snippet,
                template_section=template_section,
                seed_section=seed_section,
            )
        else:
            diff_stat = git.get_diff_stat(base_branch)
            pr_content = llm.generate_pr_content(
                config, commits, diff_stat,
                jira_snippet=jira_snippet,
                template_section=template_section,
                seed_section=seed_section,
            )

        title = pr_content["title"]
        body = pr_content["body"]

        # Show title + full body preview (no truncation)
        console.print()
        console.print(f"  [bold]Title:[/bold] {title}")
        console.print()

        console.rule("Body preview")
        console.print(body)
        console.rule()

    # 10. Edit in $EDITOR (both modes)
    if interactive:
        if click.confirm("Edit body in $EDITOR?", default=False):
            body = edit_body_in_editor(body)

    # 11. Push + create/update PR
    result = github.push_and_create_or_update(
        branch=branch,
        title=title,
        body=body,
        base=base_branch,
        draft=use_draft,
        dry_run=dry_run,
        interactive=interactive,
        existing_pr=existing_pr,
    )
    console.print()
    _print_step("PR", f"→ {result}", style="bold green")
