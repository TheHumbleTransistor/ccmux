"""NewSessionPanel — full-pane flow for creating a session from the sidebar."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.suggester import SuggestFromList
from textual.widgets import Checkbox, Input, OptionList, Static
from textual.widgets.option_list import Option

from ccmux.config import USER_CONFIG_FILE
from ccmux.ui.sidebar.repos import RepoCandidate, filter_repos, resolve_typed_path

MODE_EXISTING = "existing"
MODE_CLONE = "clone"
MODE_NEW = "new"

_MODES = (
    (MODE_EXISTING, "Existing repo", "open a repo or add a worktree"),
    (MODE_CLONE, "Clone from URL", "clone into a workspace directory"),
    (MODE_NEW, "New project", "init an empty repo in a workspace directory"),
)
_PROMPTS = {
    MODE_EXISTING: ("Repo name or path", ""),
    MODE_CLONE: ("Git URL", "Clone into:"),
    MODE_NEW: ("Project name", "Create in:"),
}
_BUSY_TEXT = {
    MODE_EXISTING: "Creating session…",
    MODE_CLONE: "Cloning…",
    MODE_NEW: "Creating project…",
}
_NO_DIRS_HINT = f"No workspace dirs. Set sidebar.workspace_dirs in {USER_CONFIG_FILE}"


class NewSessionPanel(Vertical):
    """Two-step panel: pick how to create a session, then fill in that mode's form."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("tab", "accept_suggestion", "Accept suggestion", show=False),
    ]

    class Closed(Message):
        """Posted when the user backs out of the panel."""

    class Submitted(Message):
        """Posted with the ccmux CLI arguments (without the program name) to run."""

        def __init__(self, args: list[str]) -> None:
            super().__init__()
            self.args = args

    class _BackLink(Static):
        def on_click(self) -> None:
            self.parent.action_back()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode: str | None = None
        self.busy = False
        self._candidates: list[RepoCandidate] = []
        self._workspace_dirs: list[Path] = []
        self._choice_paths: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._BackLink("[#666666]← back[/]", id="new-back")
        yield Static("New session", id="new-title")
        yield OptionList(
            *[Option(f"{label}\n[#666666]{desc}[/]", id=key) for key, label, desc in _MODES],
            id="new-modes", compact=True,
        )
        yield Static("", id="new-prompt")
        yield Input(id="new-input", compact=True)
        yield Checkbox("shallow worktree", id="new-shallow", compact=True)
        yield Static("", id="new-choices-label")
        yield OptionList(id="new-choices", compact=True)
        yield Static("", id="new-status")

    def open(self, candidates: list[RepoCandidate], workspace_dirs: list[Path]) -> None:
        """Reset to the mode list with fresh candidates and workspace dirs."""
        self._candidates = candidates
        self._workspace_dirs = list(workspace_dirs)
        self.busy = False
        self.query_one("#new-input", Input).value = ""
        self.query_one("#new-shallow", Checkbox).value = False
        self._show_modes()

    def _show_modes(self) -> None:
        self.mode = None
        self._set_busy(False)
        self._set_status("")
        self._show_form(False)
        modes = self.query_one("#new-modes", OptionList)
        modes.display = True
        modes.highlighted = 0
        modes.focus()

    def _show_form(self, visible: bool) -> None:
        for selector in ("#new-prompt", "#new-input", "#new-choices-label", "#new-choices"):
            self.query_one(selector).display = visible
        self.query_one("#new-shallow").display = visible and self.mode == MODE_EXISTING

    def _enter_mode(self, mode: str) -> None:
        self.mode = mode
        prompt, choices_label = _PROMPTS[mode]
        self.query_one("#new-modes").display = False
        self.query_one("#new-prompt", Static).update(prompt)
        self.query_one("#new-choices-label", Static).update(choices_label)
        field = self.query_one("#new-input", Input)
        field.value = ""
        field.suggester = (
            SuggestFromList([c.name for c in self._candidates], case_sensitive=False)
            if mode == MODE_EXISTING else None
        )
        self._set_status("")
        self._show_form(True)
        self._populate_choices()
        field.focus()

    def _populate_choices(self) -> None:
        choices = self.query_one("#new-choices", OptionList)
        choices.clear_options()
        if self.mode == MODE_EXISTING:
            matches = filter_repos(self._candidates, self.query_one("#new-input", Input).value)
            self._choice_paths = [c.path for c in matches]
            choices.add_options(
                Option(Text.assemble(("● ", "#d7af5f") if c.has_session else "  ", c.display))
                for c in matches
            )
        else:
            self._choice_paths = [str(d) for d in self._workspace_dirs]
            choices.add_options(Option(Text(str(d))) for d in self._workspace_dirs)
            if not self._workspace_dirs:
                self._set_status(_NO_DIRS_HINT)
        if self._choice_paths:
            choices.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "new-input" and self.mode == MODE_EXISTING and not self.busy:
            self._populate_choices()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "new-input":
            self._confirm()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "new-modes":
            self._enter_mode(event.option.id)
        elif event.option_list.id == "new-choices":
            self._confirm(choice_index=event.option_index)

    def _choice_at(self, index: int | None) -> str | None:
        if index is None or not 0 <= index < len(self._choice_paths):
            return None
        return self._choice_paths[index]

    def _confirm(self, choice_index: int | None = None) -> None:
        if self.busy or self.mode is None:
            return
        text = self.query_one("#new-input", Input).value.strip()
        if choice_index is None:
            choice_index = self.query_one("#new-choices", OptionList).highlighted
        choice = self._choice_at(choice_index)
        if self.mode == MODE_EXISTING:
            path = resolve_typed_path(text) or choice
            if path is None:
                self._set_status("No matching repo")
                return
            args = ["new", path, "-y"]
            if self.query_one("#new-shallow", Checkbox).value:
                args.append("-s")
        elif self.mode == MODE_CLONE:
            if not text:
                self._set_status("Enter a git URL")
                return
            if choice is None:
                self._set_status("Pick a directory to clone into")
                return
            args = ["clone", text, "--into", choice, "-y"]
        else:
            if not text or "/" in text:
                self._set_status("Enter a project name")
                return
            if choice is None:
                self._set_status("Pick a directory to create in")
                return
            args = ["new", str(Path(choice) / text), "--init", "-y"]
        self._set_busy(True)
        self.post_message(self.Submitted(args))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for selector in ("#new-input", "#new-choices", "#new-shallow", "#new-modes"):
            self.query_one(selector).disabled = busy
        if busy:
            self._set_status(_BUSY_TEXT[self.mode], busy=True)

    def finish(self) -> None:
        """Re-enable the form after the command succeeded."""
        self._set_busy(False)
        self._set_status("")

    def show_error(self, output: str) -> None:
        """Re-enable the form and show the last lines of a failed command's output."""
        self._set_busy(False)
        lines = [line for line in output.strip().splitlines() if line.strip()]
        self._set_status("\n".join(lines[-2:]) or "Command failed")

    def _set_status(self, text: str, busy: bool = False) -> None:
        status = self.query_one("#new-status", Static)
        status.update(Text(text))
        status.set_class(busy, "busy")

    def action_back(self) -> None:
        """Return to the mode list, or close the panel when already there."""
        if self.busy:
            return
        if self.mode is None:
            self.post_message(self.Closed())
        else:
            self._show_modes()

    def _active_list(self) -> OptionList:
        return self.query_one("#new-modes" if self.mode is None else "#new-choices", OptionList)

    def action_cursor_up(self) -> None:
        self._active_list().action_cursor_up()

    def action_cursor_down(self) -> None:
        self._active_list().action_cursor_down()

    def action_accept_suggestion(self) -> None:
        field = self.query_one("#new-input", Input)
        if self.mode is None:
            return
        if field.has_focus:
            field.action_cursor_right()
        else:
            field.focus()
