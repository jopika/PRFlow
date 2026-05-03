"""Interactive TUI file picker for staged commit selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

class FileStatusCategory(Enum):
    Staged = "staged"
    Unstaged = "unstaged"
    Untracked = "untracked"

_CATEGORY_STYLE = {
    FileStatusCategory.Staged: "fg:ansigreen",
    FileStatusCategory.Unstaged: "fg:ansiyellow",
    FileStatusCategory.Untracked: "fg:ansibrightblack",
}

@dataclass
class PickerFile:
    """A file shown in the picker, with its git status category."""
    path: str
    category: FileStatusCategory


@dataclass
class PickerResult:
    """Result returned by CommitPicker.run()."""
    selected_files: list[PickerFile]
    message: str | None  # None or "" → generate with LLM


@dataclass
class _State:
    files: list[PickerFile]
    cursor: int = 0
    selected: set[int] = field(default_factory=set)  # starts empty — user selects explicitly
    screen: str = "picker"  # "picker" | "confirm"
    last_key: str = ""  # tracks previous key for double-key abort
    confirmed: bool = False
    aborted: bool = False


class CommitPicker:
    """Two-panel interactive TUI: file selection → commit message.

    Returns a PickerResult on confirm, or None on abort / no selection.
    Accepts optional ``input`` and ``output`` for testing (prompt_toolkit's
    ``create_pipe_input()`` / ``DummyOutput()``).

    ``view_diff_fn(path, category)`` is called (via run_in_terminal) when the
    user presses I on a file — the caller is responsible for opening the pager.
    """

    _files: list[PickerFile]
    _view_diff_fn: Callable[[str, FileStatusCategory], None]
    _pt_input: Any
    _pt_output: Any
    _state: _State
    _message_field: TextArea

    def __init__(
        self,
        files: list[PickerFile],
        view_diff_fn: Callable[[str, FileStatusCategory], None],
        *,
        input: Any = None,  # noqa: A002
        output: Any = None,
    ) -> None:
        self._files = files
        self._view_diff_fn = view_diff_fn
        self._pt_input = input
        self._pt_output = output
        self._state = _State(files=files)
        self._message_field = TextArea(
            multiline=False,
            prompt="  > ",
            focusable=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> PickerResult | None:
        """Run the picker TUI. Returns None if aborted or nothing selected."""
        if not self._files:
            return None

        s = self._state
        kb = self._build_key_bindings()

        def get_container() -> HSplit | Window:
            if s.screen == "confirm":
                return HSplit([
                    Window(
                        content=FormattedTextControl(self._render_confirm_header),
                        dont_extend_height=True,
                    ),
                    self._message_field,
                    Window(
                        content=FormattedTextControl(self._render_confirm_footer),
                        height=1,
                        dont_extend_height=True,
                    ),
                ])
            return Window(content=FormattedTextControl(self._render_picker))

        body = DynamicContainer(get_container)
        layout = Layout(body)

        app = Application(
            layout=layout,
            key_bindings=kb,
            erase_when_done=True,
            input=self._pt_input,
            output=self._pt_output,
        )
        app.run()

        if s.aborted or not s.confirmed or not s.selected:
            return None

        selected_files = [self._files[i] for i in sorted(s.selected)]
        message = self._message_field.text.strip() or None
        return PickerResult(selected_files=selected_files, message=message)

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        s = self._state

        @Condition
        def in_picker() -> bool:
            return s.screen == "picker"

        @Condition
        def in_confirm() -> bool:
            return s.screen == "confirm"

        def _reset() -> None:
            s.last_key = ""

        # -- Picker: navigation --

        @kb.add("up", filter=in_picker)
        @kb.add("k", filter=in_picker)
        def move_up(event: Any) -> None:
            _reset()
            s.cursor = max(0, s.cursor - 1)

        @kb.add("down", filter=in_picker)
        @kb.add("j", filter=in_picker)
        def move_down(event: Any) -> None:
            _reset()
            s.cursor = min(len(s.files) - 1, s.cursor + 1)

        # -- Picker: selection --

        @kb.add("space", filter=in_picker)
        @kb.add("enter", filter=in_picker)
        def toggle_file(event: Any) -> None:
            _reset()
            if s.cursor in s.selected:
                s.selected.discard(s.cursor)
            else:
                s.selected.add(s.cursor)

        @kb.add("a", filter=in_picker)
        @kb.add("A", filter=in_picker)
        def toggle_all(event: Any) -> None:
            _reset()
            all_idx = set(range(len(s.files)))
            s.selected = set() if s.selected == all_idx else all_idx

        # -- Picker: view diff via pager --

        @kb.add("i", filter=in_picker)
        @kb.add("I", filter=in_picker)
        def show_diff(event: Any) -> None:
            _reset()
            pf = s.files[s.cursor]
            self._view_diff_fn(pf.path, pf.category)

        # -- Navigate picker ↔ confirm --

        @kb.add("right", filter=in_picker)
        @kb.add("tab", filter=in_picker, eager=True)
        def go_to_confirm(event: Any) -> None:
            _reset()
            s.screen = "confirm"
            event.app.layout.focus(self._message_field)

        @kb.add("left", filter=in_confirm)
        @kb.add("tab", filter=in_confirm, eager=True)
        def go_to_picker(event: Any) -> None:
            _reset()
            s.screen = "picker"

        # -- Confirm: submit --

        @kb.add("enter", filter=in_confirm, eager=True)
        def do_commit(event: Any) -> None:
            _reset()
            s.confirmed = True
            event.app.exit()

        # -- Double-key abort --

        @kb.add("escape", filter=in_picker | in_confirm, eager=True)
        def handle_escape(event: Any) -> None:
            if s.last_key == "escape":
                s.aborted = True
                event.app.exit()
            else:
                s.last_key = "escape"

        @kb.add("c-c")
        def handle_ctrl_c(event: Any) -> None:
            if s.last_key == "c-c":
                s.aborted = True
                event.app.exit()
            else:
                s.last_key = "c-c"

        return kb

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def _render_picker(self) -> FormattedText:
        s = self._state
        n_sel = len(s.selected)
        n_tot = len(s.files)
        out: list[tuple[str, str]] = []

        out.append(("bold", f" Select files to commit  ({n_sel}/{n_tot} selected)\n"))
        out.append(("", " " + "─" * 53 + "\n"))

        current_category: FileStatusCategory | None = None
        for i, pf in enumerate(s.files):
            if pf.category != current_category:
                current_category = pf.category
                label = pf.category.value.capitalize()
                out.append(("bold", f" {label}\n"))

            is_cursor = i == s.cursor
            is_selected = i in s.selected
            cursor_mark = "▶" if is_cursor else " "
            check_mark = "x" if is_selected else " "
            cat_style = _CATEGORY_STYLE.get(pf.category, "")

            if is_cursor and is_selected:
                style = f"bold {cat_style}"
            elif is_cursor:
                style = "bold"
            elif is_selected:
                style = cat_style
            else:
                style = "fg:ansibrightblack" if pf.category == FileStatusCategory.Untracked else ""

            out += [
                ("", f"   {cursor_mark} "),
                (style, f"[{check_mark}]"),
                ("", " "),
                (style, pf.path),
                ("", "\n"),
            ]

        out.append(("", "\n"))
        out.append(("italic", "   ↑↓ navigate   Space/Enter toggle   A all   I diff   →/Tab confirm   Esc×2 abort\n"))
        return FormattedText(out)

    def _render_confirm_header(self) -> FormattedText:
        s = self._state
        n = len(s.selected)
        out: list[tuple[str, str]] = []

        out.append(("bold", f" Commit  ({n} file{'s' if n != 1 else ''} selected)\n"))
        out.append(("", " " + "─" * 53 + "\n"))

        if s.selected:
            for i in sorted(s.selected):
                pf = s.files[i]
                cat_style = _CATEGORY_STYLE.get(pf.category, "")
                out.append((cat_style, f"   {pf.path}\n"))
        else:
            out.append(("fg:ansiyellow", "   (no files selected — go back and select files)\n"))

        out.append(("", "\n"))
        out.append(("italic", " Message (blank = generate with LLM):\n"))
        return FormattedText(out)

    def _render_confirm_footer(self) -> FormattedText:
        return FormattedText([
            ("italic", "   ←/Tab back   Enter commit   Esc×2 abort"),
        ])
