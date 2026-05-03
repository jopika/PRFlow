"""Tests for prflow/picker.py — interactive TUI file picker."""

from __future__ import annotations

import pytest

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from prflow.picker import CommitPicker, FileStatusCategory, PickerFile, PickerResult

# Key sequences (ANSI)
UP = "\x1b[A"
DOWN = "\x1b[B"
RIGHT = "\x1b[C"  # go to confirm
LEFT = "\x1b[D"   # go back to picker
SPACE = " "
ENTER = "\r"
TAB = "\t"
ESC = "\x1b"
CTRL_C = "\x03"


def _staged(*paths) -> list[PickerFile]:
    return [PickerFile(path=p, category=FileStatusCategory.Staged) for p in paths]


def _mixed() -> list[PickerFile]:
    return [
        PickerFile(path="a.py", category=FileStatusCategory.Staged),
        PickerFile(path="b.py", category=FileStatusCategory.Unstaged),
        PickerFile(path="c.txt", category=FileStatusCategory.Untracked),
    ]


def run_picker(
    files: list[PickerFile],
    keys: str,
    view_diff_fn=None,
) -> PickerResult | None:
    """Run CommitPicker with the given key sequence and return the result."""
    view_calls: list[tuple[str, str]] = []

    def default_view(path: str, category: str) -> None:
        view_calls.append((path, category))

    with create_pipe_input() as inp:
        inp.send_text(keys)
        picker = CommitPicker(
            files=files,
            view_diff_fn=view_diff_fn or default_view,
            input=inp,
            output=DummyOutput(),
        )
        result = picker.run()

    # Attach captured view calls for assertions
    if result is not None:
        result._view_calls = view_calls  # type: ignore[attr-defined]
    return result


class TestFileSelection:
    def test_nothing_selected_confirm_returns_none(self):
        result = run_picker(_staged("a.py"), RIGHT + ENTER)
        assert result is None

    def test_space_selects_first_file(self):
        result = run_picker(_staged("a.py", "b.py"), SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["a.py"]

    def test_enter_also_toggles(self):
        result = run_picker(_staged("a.py", "b.py"), ENTER + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["a.py"]

    def test_navigate_down_then_select(self):
        result = run_picker(_staged("a.py", "b.py"), DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["b.py"]

    def test_multiple_selections(self):
        result = run_picker(_staged("a.py", "b.py", "c.py"), SPACE + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["a.py", "b.py"]

    def test_toggle_deselects(self):
        result = run_picker(_staged("a.py", "b.py"), SPACE + SPACE + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["b.py"]

    def test_cursor_stays_at_top(self):
        result = run_picker(_staged("a.py", "b.py"), UP + SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["a.py"]

    def test_cursor_stays_at_bottom(self):
        files = _staged("a.py", "b.py", "c.py")
        result = run_picker(files, DOWN + DOWN + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert [pf.path for pf in result.selected_files] == ["c.py"]

    def test_toggle_all_selects_all(self):
        files = _staged("a.py", "b.py", "c.py")
        result = run_picker(files, "a" + RIGHT + ENTER)
        assert result is not None
        assert len(result.selected_files) == 3

    def test_toggle_all_twice_deselects_all(self):
        result = run_picker(_staged("a.py", "b.py"), "a" + "a" + RIGHT + ENTER)
        assert result is None

    def test_toggle_all_partial_selects_all(self):
        files = _staged("a.py", "b.py", "c.py")
        result = run_picker(files, SPACE + "a" + RIGHT + ENTER)
        assert result is not None
        assert len(result.selected_files) == 3

    def test_single_file(self):
        result = run_picker(_staged("only.py"), SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "only.py"

    def test_empty_file_list_returns_none(self):
        result = run_picker([], "")
        assert result is None


class TestMixedCategories:
    def test_unstaged_file_selectable(self):
        result = run_picker(_mixed(), DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "b.py"
        assert result.selected_files[0].category == FileStatusCategory.Unstaged

    def test_untracked_file_selectable(self):
        result = run_picker(_mixed(), DOWN + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "c.txt"
        assert result.selected_files[0].category == FileStatusCategory.Untracked

    def test_mixed_selection_preserves_categories(self):
        result = run_picker(_mixed(), SPACE + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        categories = {pf.category for pf in result.selected_files}
        assert FileStatusCategory.Staged in categories
        assert FileStatusCategory.Unstaged in categories

    def test_selected_files_sorted_by_index(self):
        # Select third then first
        result = run_picker(_mixed(), DOWN + DOWN + SPACE + UP + UP + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "a.py"
        assert result.selected_files[1].path == "c.txt"


class TestNavigation:
    def test_tab_navigates_to_confirm(self):
        result = run_picker(_staged("a.py"), SPACE + TAB + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "a.py"

    def test_right_then_left_returns_to_picker(self):
        result = run_picker(_staged("a.py", "b.py"), RIGHT + LEFT + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "b.py"

    def test_tab_in_confirm_goes_back(self):
        result = run_picker(_staged("a.py", "b.py"), RIGHT + TAB + DOWN + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "b.py"


class TestAbort:
    def test_double_escape_aborts(self):
        assert run_picker(_staged("a.py"), ESC + ESC) is None

    def test_single_escape_does_not_abort(self):
        result = run_picker(_staged("a.py"), ESC + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "a.py"

    def test_double_ctrl_c_aborts(self):
        assert run_picker(_staged("a.py"), CTRL_C + CTRL_C) is None

    def test_escape_resets_after_other_key(self):
        # Esc, then down (resets last_key), then Esc — should NOT abort
        result = run_picker(_staged("a.py", "b.py"), ESC + DOWN + ESC + SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.selected_files[0].path == "b.py"


class TestDiffView:
    def test_i_calls_view_diff_fn(self):
        calls: list[tuple[str, FileStatusCategory]] = []

        def record(path: str, category: FileStatusCategory) -> None:
            calls.append((path, category))

        run_picker(_staged("a.py"), "i" + SPACE + RIGHT + ENTER, view_diff_fn=record)
        assert ("a.py", FileStatusCategory.Staged) in calls

    def test_diff_called_for_highlighted_file(self):
        calls: list[tuple[str, FileStatusCategory]] = []

        def record(path: str, category: FileStatusCategory) -> None:
            calls.append((path, category))

        run_picker(_staged("a.py", "b.py"), DOWN + "i" + SPACE + RIGHT + ENTER, view_diff_fn=record)
        assert calls[0] == ("b.py", FileStatusCategory.Staged)

    def test_diff_passes_correct_category(self):
        calls: list[tuple[str, FileStatusCategory]] = []

        def record(path: str, category: FileStatusCategory) -> None:
            calls.append((path, category))

        run_picker(_mixed(), DOWN + "i" + SPACE + RIGHT + ENTER, view_diff_fn=record)
        assert calls[0] == ("b.py", FileStatusCategory.Unstaged)


class TestCommitMessage:
    def test_blank_message_returns_none(self):
        result = run_picker(_staged("a.py"), SPACE + RIGHT + ENTER)
        assert result is not None
        assert result.message is None

    def test_typed_message_returned(self):
        result = run_picker(_staged("a.py"), SPACE + RIGHT + "my commit msg" + ENTER)
        assert result is not None
        assert result.message == "my commit msg"

    def test_whitespace_only_message_returns_none(self):
        result = run_picker(_staged("a.py"), SPACE + RIGHT + "   " + ENTER)
        assert result is not None
        assert result.message is None
