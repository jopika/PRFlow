"""Tests for update.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from prflow import update


def _bump_patch(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


class TestVersionHelpers:
    def test_normalize_version_strips_v_prefix(self):
        assert update.normalize_version("v0.2.1") == "0.2.1"

    def test_is_newer_version_true(self):
        assert update.is_newer_version("0.2.2", "0.2.1") is True

    def test_is_newer_version_false_for_same(self):
        assert update.is_newer_version("0.2.1", "0.2.1") is False

    def test_is_newer_version_false_for_invalid(self):
        assert update.is_newer_version("release-latest", "0.2.1") is False


class TestReleaseLookup:
    def test_get_latest_release_info_extracts_wheel_url(self, mocker):
        payload = {
            "tag_name": "v0.3.2",
            "html_url": "https://example.com/release",
            "assets": [
                {"browser_download_url": "https://example.com/prflow-0.3.2-py3-none-any.whl"},
            ],
        }
        response = mocker.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        mocker.patch("prflow.update.request.urlopen", return_value=response)
        mocker.patch("prflow.update.json.load", return_value=payload)

        info = update.get_latest_release_info("jopika/PRFlow")

        assert info.latest_version == "0.3.2"
        assert info.release_url == "https://example.com/release"
        assert info.wheel_url == "https://example.com/prflow-0.3.2-py3-none-any.whl"
        assert info.error is None


class TestCheckTiming:
    def test_check_due_with_no_timestamp(self):
        assert update.is_check_due({}, 24) is True

    def test_check_not_due_inside_interval(self):
        now = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
        state = {"last_checked_at": (now - timedelta(hours=1)).isoformat()}
        assert update.is_check_due(state, 24, now) is False


class TestCheckForUpdates:
    _config = {
        "updates": {
            "enabled": True,
            "check_interval_hours": 24,
            "github_repo": "jopika/PRFlow",
        }
    }

    def test_force_check_updates_state_and_reports_newer_version(self, mocker):
        now = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
        newer_version = _bump_patch(update.__version__)
        mocker.patch("prflow.update.load_state", return_value={})
        save_state = mocker.patch("prflow.update.save_state")

        status, state = update.check_for_updates(
            self._config,
            force=True,
            now=now,
            fetch_release=lambda repo: (newer_version, "https://example.com/release", None),
        )

        assert status.checked is True
        assert status.update_available is True
        assert status.latest_version == newer_version
        assert state["latest_seen_version"] == newer_version
        save_state.assert_called_once()

    def test_uses_cached_version_when_throttled(self, mocker):
        now = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
        state = {
            "last_checked_at": now.isoformat(),
            "latest_seen_version": "99.0.0",
            "latest_release_url": "https://example.com/release",
        }
        mocker.patch("prflow.update.load_state", return_value=state.copy())
        fetcher = mocker.Mock()

        status, _ = update.check_for_updates(
            self._config,
            force=False,
            now=now,
            fetch_release=fetcher,
        )

        assert status.checked is False
        assert status.update_available is True
        fetcher.assert_not_called()

    def test_disabled_updates_skip_check(self, mocker):
        mocker.patch("prflow.update.load_state", return_value={})
        fetcher = mocker.Mock()

        status, _ = update.check_for_updates(
            {"updates": {"enabled": False}},
            force=False,
            fetch_release=fetcher,
        )

        assert status.update_available is False
        fetcher.assert_not_called()

    def test_clears_seen_update_when_current_is_latest(self, mocker):
        state = {
            "latest_seen_version": update.__version__,
            "last_prompted_version": update.__version__,
            "last_declined_version": update.__version__,
        }
        mocker.patch("prflow.update.load_state", return_value=state)
        save_state = mocker.patch("prflow.update.save_state")

        status, cleared_state = update.check_for_updates(
            self._config,
            force=False,
            fetch_release=lambda repo: (None, None, None),
        )

        assert status.update_available is False
        assert "last_prompted_version" not in cleared_state
        assert "last_declined_version" not in cleared_state
        save_state.assert_called_once()

    def test_failed_check_sets_error(self, mocker):
        now = datetime(2026, 4, 8, 12, tzinfo=timezone.utc)
        mocker.patch("prflow.update.load_state", return_value={})

        status, _ = update.check_for_updates(
            self._config,
            force=False,
            now=now,
            fetch_release=lambda repo: (None, None, "timed out"),
        )

        assert status.error == "timed out"


class TestStartupUpdateHandling:
    def test_first_seen_update_prompts_once(self, mocker):
        current_version = update.__version__
        newer_version = _bump_patch(current_version)
        status = update.UpdateStatus(
            current_version=current_version,
            latest_version=newer_version,
            update_available=True,
        )
        state = {}
        mocker.patch("prflow.update.load_state", return_value={})
        mocker.patch("prflow.update.is_check_due", return_value=True)
        mocker.patch("prflow.update.check_for_updates", return_value=(status, state))
        mock_confirm = mocker.patch("prflow.update.click.confirm", return_value=False)
        save_state = mocker.patch("prflow.update.save_state")
        show_banner = mocker.patch("prflow.update.show_update_banner")
        mock_console = mocker.patch("prflow.update.console")

        update.handle_startup_update({"updates": {"enabled": True}}, interactive=True)

        mock_confirm.assert_called_once()
        assert state["last_prompted_version"] == newer_version
        assert state["last_declined_version"] == newer_version
        show_banner.assert_not_called()
        assert save_state.call_count == 2
        rendered = [str(call) for call in mock_console.print.call_args_list]
        assert any("Checking for prflow updates" in line for line in rendered)

    def test_declined_update_shows_banner_on_later_runs(self, mocker):
        current_version = update.__version__
        newer_version = _bump_patch(current_version)
        status = update.UpdateStatus(
            current_version=current_version,
            latest_version=newer_version,
            update_available=True,
        )
        state = {"last_prompted_version": newer_version, "last_declined_version": newer_version}
        mocker.patch("prflow.update.load_state", return_value=state.copy())
        mocker.patch("prflow.update.is_check_due", return_value=False)
        mocker.patch("prflow.update.check_for_updates", return_value=(status, state))
        show_banner = mocker.patch("prflow.update.show_update_banner")
        mock_confirm = mocker.patch("prflow.update.click.confirm")

        update.handle_startup_update({"updates": {"enabled": True}}, interactive=True)

        show_banner.assert_called_once_with(status)
        mock_confirm.assert_not_called()

    def test_non_interactive_mode_shows_banner_without_prompt(self, mocker):
        current_version = update.__version__
        newer_version = _bump_patch(current_version)
        status = update.UpdateStatus(
            current_version=current_version,
            latest_version=newer_version,
            update_available=True,
        )
        mocker.patch("prflow.update.load_state", return_value={})
        mocker.patch("prflow.update.is_check_due", return_value=False)
        mocker.patch("prflow.update.check_for_updates", return_value=(status, {}))
        show_banner = mocker.patch("prflow.update.show_update_banner")
        mock_confirm = mocker.patch("prflow.update.click.confirm")

        update.handle_startup_update({"updates": {"enabled": True}}, interactive=False)

        show_banner.assert_called_once_with(status)
        mock_confirm.assert_not_called()

    def test_failed_startup_check_prints_small_message_and_continues(self, mocker):
        status = update.UpdateStatus(current_version="0.2.1", error="timed out")
        mocker.patch("prflow.update.load_state", return_value={})
        mocker.patch("prflow.update.is_check_due", return_value=True)
        mocker.patch("prflow.update.check_for_updates", return_value=(status, {}))
        mock_console = mocker.patch("prflow.update.console")

        update.handle_startup_update({"updates": {"enabled": True}}, interactive=True)

        rendered = [str(call) for call in mock_console.print.call_args_list]
        assert any("Checking for prflow updates" in line for line in rendered)
        assert any("Update check skipped: timed out" in line for line in rendered)


class TestManualUpdate:
    def test_manual_update_checks_and_prints_up_to_date(self, mocker):
        status = update.UpdateStatus(
            current_version=update.__version__,
            latest_version=update.__version__,
            checked=True,
        )
        mocker.patch("prflow.update.check_for_updates", return_value=(status, {}))
        mock_console = mocker.patch("prflow.update.console")

        update.handle_manual_update({"updates": {"enabled": True}})

        rendered = [str(call) for call in mock_console.print.call_args_list]
        assert any("up to date" in line for line in rendered)

    def test_manual_update_runs_upgrade_when_confirmed(self, mocker):
        current_version = update.__version__
        newer_version = _bump_patch(current_version)
        status = update.UpdateStatus(
            current_version=current_version,
            latest_version=newer_version,
            release_url="https://example.com/release",
            checked=True,
            update_available=True,
        )
        state = {}
        mocker.patch("prflow.update.check_for_updates", return_value=(status, state))
        mocker.patch("prflow.update.click.confirm", return_value=True)
        run_upgrade = mocker.patch("prflow.update.run_upgrade", return_value=True)
        save_state = mocker.patch("prflow.update.save_state")

        update.handle_manual_update({"updates": {"enabled": True}})

        run_upgrade.assert_called_once_with({"updates": {"enabled": True}})
        assert "last_prompted_version" not in state
        save_state.assert_called()


class TestRunUpgrade:
    def test_run_upgrade_installs_latest_release_wheel(self, mocker):
        mocker.patch("prflow.update.shutil.which", return_value="/usr/bin/pipx")
        mocker.patch(
            "prflow.update.get_latest_release_info",
            return_value=update.ReleaseInfo(
                latest_version="0.3.2",
                wheel_url="https://example.com/prflow-0.3.2-py3-none-any.whl",
            ),
        )
        subprocess_run = mocker.patch("prflow.update.subprocess.run")
        subprocess_run.return_value.returncode = 0
        mock_console = mocker.patch("prflow.update.console")

        result = update.run_upgrade({"updates": {"github_repo": "jopika/PRFlow"}})

        assert result is True
        subprocess_run.assert_called_once()
        args, kwargs = subprocess_run.call_args
        assert args[0] == [
            "pipx",
            "install",
            "--force",
            "https://example.com/prflow-0.3.2-py3-none-any.whl",
        ]
        assert "0.3.2" in str(mock_console.print.call_args_list[-1])

    def test_run_upgrade_fails_when_release_has_no_wheel(self, mocker):
        mocker.patch("prflow.update.shutil.which", return_value="/usr/bin/pipx")
        mocker.patch(
            "prflow.update.get_latest_release_info",
            return_value=update.ReleaseInfo(latest_version="0.3.2"),
        )
        mocker.patch("prflow.update.subprocess.run")
        mock_console = mocker.patch("prflow.update.console")

        result = update.run_upgrade({"updates": {"github_repo": "jopika/PRFlow"}})

        assert result is False
        rendered = [str(call) for call in mock_console.print.call_args_list]
        assert any("does not include a wheel asset" in line for line in rendered)
