"""Best-effort self-update checks for prflow."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, request

import click
import yaml
from rich.console import Console

from prflow import __version__

console = Console()

STATE_FILE = ".prflow-state.yaml"


@dataclass
class UpdateStatus:
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    checked: bool = False
    update_available: bool = False
    error: str | None = None


def state_path() -> Path:
    """Location for transient per-user update state."""
    return Path.home() / STATE_FILE


def load_state() -> dict:
    """Load update state, returning {} for missing or invalid files."""
    path = state_path()
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError:
        return {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    """Persist update state. Errors are ignored to keep checks non-blocking."""
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.safe_dump(state, f, sort_keys=False)
    except OSError:
        return


def normalize_version(version: str | None) -> str | None:
    """Normalize tags like v0.2.1 into bare versions."""
    if not isinstance(version, str):
        return None
    normalized = version.strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return normalized or None


def version_key(version: str | None) -> tuple[int, ...] | None:
    """Convert dot-separated numeric versions into a comparable tuple."""
    normalized = normalize_version(version)
    if not normalized:
        return None

    parts = normalized.split(".")
    values: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        values.append(int(part))
    return tuple(values)


def is_newer_version(candidate: str | None, current: str | None) -> bool:
    """Return True if candidate is a strictly newer version than current."""
    candidate_key = version_key(candidate)
    current_key = version_key(current)
    if candidate_key is None or current_key is None:
        return False
    return candidate_key > current_key


def get_latest_release(repo: str, timeout: float = 2.0) -> tuple[str | None, str | None, str | None]:
    """Fetch the latest release version and URL from GitHub Releases."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"prflow/{__version__}",
    }
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
    except error.HTTPError as exc:
        return None, None, f"HTTP {exc.code}"
    except error.URLError as exc:
        reason = getattr(exc, "reason", None)
        return None, None, str(reason) if reason else "network error"
    except TimeoutError:
        return None, None, "timed out"
    except OSError as exc:
        return None, None, str(exc)
    except json.JSONDecodeError:
        return None, None, "invalid response"

    latest_version = normalize_version(payload.get("tag_name") or payload.get("name"))
    release_url = payload.get("html_url")
    if not isinstance(release_url, str):
        release_url = None
    return latest_version, release_url, None


def clear_seen_update(state: dict) -> dict:
    """Remove reminder state once the user is current again."""
    for key in (
        "latest_seen_version",
        "latest_release_url",
        "last_prompted_version",
        "last_declined_version",
    ):
        state.pop(key, None)
    return state


def is_check_due(state: dict, interval_hours: int, now: datetime | None = None) -> bool:
    """Return True when the throttled check window has elapsed."""
    timestamp = state.get("last_checked_at")
    if not isinstance(timestamp, str):
        return True

    try:
        last_checked = datetime.fromisoformat(timestamp)
    except ValueError:
        return True

    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)

    now = now or datetime.now(timezone.utc)
    return now - last_checked >= timedelta(hours=interval_hours)


def _updates_config(config: dict) -> dict:
    return config.get("updates", {})


def check_for_updates(
    config: dict,
    *,
    force: bool = False,
    now: datetime | None = None,
    fetch_release=get_latest_release,
) -> tuple[UpdateStatus, dict]:
    """Check GitHub Releases for a newer prflow version."""
    state = load_state()
    updates_cfg = _updates_config(config)
    current_version = normalize_version(__version__) or __version__
    status = UpdateStatus(current_version=current_version)

    if not updates_cfg.get("enabled", True) and not force:
        return status, state

    repo = updates_cfg.get("github_repo", "jopika/PRFlow")
    interval_hours = int(updates_cfg.get("check_interval_hours", 24))
    now = now or datetime.now(timezone.utc)
    mutated = False

    latest_version = normalize_version(state.get("latest_seen_version"))
    release_url = state.get("latest_release_url")
    if not isinstance(release_url, str):
        release_url = None

    if force or is_check_due(state, interval_hours, now):
        fetched_version, fetched_url, fetch_error = fetch_release(repo)
        status.checked = True
        if fetched_version:
            latest_version = fetched_version
            release_url = fetched_url
            state["last_checked_at"] = now.isoformat()
            state["latest_seen_version"] = latest_version
            if release_url:
                state["latest_release_url"] = release_url
            else:
                state.pop("latest_release_url", None)
            mutated = True
        else:
            status.error = fetch_error or "Unable to check for updates right now."

    status.latest_version = latest_version
    status.release_url = release_url
    status.update_available = is_newer_version(latest_version, current_version)

    if not status.update_available and latest_version is not None:
        clear_seen_update(state)
        mutated = True

    if mutated:
        save_state(state)

    return status, state


def _banner_text(status: UpdateStatus) -> str:
    message = (
        f"[yellow]Update available:[/yellow] prflow {status.latest_version} "
        f"(current {status.current_version}). Run [bold]prflow --update[/bold] to upgrade."
    )
    if status.release_url:
        message += f" [dim]{status.release_url}[/dim]"
    return message


def show_update_banner(status: UpdateStatus) -> None:
    """Print the non-intrusive startup banner."""
    console.print(_banner_text(status))


def run_upgrade() -> bool:
    """Run the supported upgrade command."""
    if shutil.which("pipx") is None:
        console.print(
            "[yellow]pipx is not installed or not on PATH.[/yellow] "
            "Install pipx first, then run [bold]pipx upgrade prflow[/bold]."
        )
        return False

    cwd = Path.home() # Override cwd to home to minimize name collision for pipx

    result = subprocess.run(["pipx", "upgrade", "prflow"], cwd=str(cwd))
    if result.returncode == 0:
        console.print("[green]prflow was updated successfully.[/green]")
        return True

    console.print("[bold red]Update failed.[/bold red] Try [bold]pipx upgrade prflow[/bold] manually.")
    return False


def handle_manual_update(config: dict) -> None:
    """Handle the explicit `prflow --update` flow."""
    status, state = check_for_updates(config, force=True)

    if status.error and status.latest_version is None:
        console.print(f"[yellow]{status.error}[/yellow]")
        return

    if not status.update_available:
        console.print(f"[green]prflow {status.current_version} is up to date.[/green]")
        return

    console.print(f"Current version: [bold]{status.current_version}[/bold]")
    console.print(f"Latest version: [bold]{status.latest_version}[/bold]")
    if status.release_url:
        console.print(f"Release notes: {status.release_url}")

    state["last_prompted_version"] = status.latest_version
    save_state(state)

    if click.confirm("Upgrade now with pipx?", default=False):
        if run_upgrade():
            clear_seen_update(state)
            save_state(state)


def handle_startup_update(config: dict, interactive: bool) -> None:
    """Best-effort update check for normal CLI startup."""
    updates_cfg = _updates_config(config)
    if not updates_cfg.get("enabled", True):
        return

    state = load_state()
    interval_hours = int(updates_cfg.get("check_interval_hours", 24))
    check_announced = is_check_due(state, interval_hours)
    if check_announced:
        console.print("[dim]Checking for prflow updates...[/dim]")

    status, state = check_for_updates(config, force=False)
    if status.error:
        console.print(f"[dim]Update check skipped: {status.error}[/dim]")
        return

    if not status.update_available:
        return

    latest_version = status.latest_version
    if latest_version is None:
        return

    if interactive and state.get("last_prompted_version") != latest_version:
        console.print(_banner_text(status))
        state["last_prompted_version"] = latest_version
        save_state(state)

        if click.confirm("Upgrade now with pipx?", default=False):
            if run_upgrade():
                clear_seen_update(state)
                save_state(state)
            return

        state["last_declined_version"] = latest_version
        save_state(state)
        return

    show_update_banner(status)
