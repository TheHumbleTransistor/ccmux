"""SessionRow — variable-height widget with tree characters, indicator, name, git info, and optional note."""

import time

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static, TextArea


class NoteInput(TextArea):
    """Multi-line note editor: Enter submits, Shift+Enter / Ctrl+Enter inserts newline."""

    class Submitted(Message):
        """Posted when the user presses Enter (without modifier) to save."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    async def _on_key(self, event: events.Key) -> None:
        if self.read_only:
            return
        if event.key == "enter":
            # Plain Enter → submit
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self.text))
        elif event.key in ("shift+enter", "ctrl+enter"):
            # Modifier+Enter → insert newline (treat as plain enter for TextArea)
            event.prevent_default()
            event.stop()
            self.insert("\n")
        else:
            await super()._on_key(event)


class SessionRow(Vertical):
    """A clickable 4-line row showing tree hierarchy, session status, name, and git info."""

    # Breathing animation: dot color steps for one full cycle (grey→green→grey).
    # Uses exact 256-color palette entries to avoid rounding artifacts in tmux.
    #   247=#9e9e9e  108=#87af87  71=#5faf5f  77=#5fd75f  40=#00d700  46=#00ff00
    _BREATH_COLORS = [
        "#9e9e9e",  # 247 — grey (rest)
        "#87af87",  # 108
        "#5faf5f",  #  71
        "#5fd75f",  #  77
        "#00d700",  #  40
        "#00ff00",  #  46 — green (peak)
        "#00d700",  #  40
        "#5fd75f",  #  77
        "#5faf5f",  #  71
        "#87af87",  # 108
    ]
    _BREATH_INTERVAL = 0.2  # seconds between color steps (10 × 0.2s = 2s cycle)

    class Selected(Message):
        """Posted when the user clicks a session row."""

        def __init__(self, session_name: str, session_id: int = 0) -> None:
            super().__init__()
            self.session_name = session_name
            self.session_id = session_id

    class NoteEdited(Message):
        """Posted when the user edits a session note via double-click."""

        def __init__(self, session_name: str, note: str) -> None:
            super().__init__()
            self.session_name = session_name
            self.note = note

    def __init__(
        self,
        session_name: str,
        session_type: str,
        is_active: bool,
        is_current: bool,
        status: str = "idle",
        has_blocker_alert: bool = False,
        is_last: bool = False,
        branch: str | None = None,
        short_sha: str = "",
        lines_added: int = 0,
        lines_removed: int = 0,
        session_id: int = 0,
        note: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session_name = session_name
        self.session_id = session_id
        self.note = note
        self._last_click_time: float = 0
        self._editing: bool = False
        self.session_type = session_type
        self.is_active = is_active
        self.is_current = is_current
        self.status = status
        self.has_blocker_alert = has_blocker_alert
        self.is_last = is_last
        self.branch = branch
        self.short_sha = short_sha
        self.lines_added = lines_added
        self.lines_removed = lines_removed
        self._flash_timer = None
        self._edit_timeout_timer = None
        self._breath_timer = None
        self._breath_frame = 0
        self._breath_offset = hash(session_name) % len(self._BREATH_COLORS)
        if is_current:
            self.add_class("current")
        self._apply_blocker_alert_class(has_blocker_alert)
        self._update_flash()
        self._update_breathing()

    def _tree_chars(self) -> tuple[str, str, str]:
        """Return (top, branch, tail) tree characters."""
        if self.is_last:
            return ("│", "└── ", "")
        return ("│", "├── ", "│")

    def _format_name_text(self) -> str:
        """Build the name text (without worktree suffix — that's a separate widget)."""
        branch_char = self._tree_chars()[1]
        if self.status == "deactivated":
            indicator = "\u25cb"  # ○ grey
        elif self.status == "blocked":
            indicator = "[#d70000]\u25cf[/]"  # ● static red
        elif self.status == "active" and self._breath_timer is not None:
            color = self._BREATH_COLORS[(self._breath_frame + self._breath_offset) % len(self._BREATH_COLORS)]
            indicator = f"[{color}]\u25cf[/]"  # ● animated green
        else:
            indicator = "\u25cf"  # ● grey (idle)
        return f"{branch_char}{indicator} {self.session_name}"

    def _tree_prefix(self) -> str:
        """Return the tree-drawing prefix for line3."""
        return "│     " if not self.is_last else "      "

    def _format_branch_text(self) -> str:
        """Build the branch/ref text (without tree prefix)."""
        if self.branch is not None:
            ref_text = self.branch
        elif self.short_sha:
            ref_text = f"HEAD: {self.short_sha}"
        else:
            return ""

        # Truncate ref to fit: sidebar is ~39 usable chars, prefix is 6
        max_ref = 39 - 6
        return ref_text[:max_ref] if max_ref > 0 else ""

    def compose(self) -> ComposeResult:
        top, branch_char, tail = self._tree_chars()
        yield Static(top, classes="line1")
        with Horizontal(classes="line2"):
            yield Static(self._format_name_text(), classes="name")
            if self.session_type == "worktree":
                yield Static(" (worktree)", classes="worktree-suffix")
        with Horizontal(classes="line3"):
            yield Static(self._tree_prefix(), classes="tree-prefix")
            yield Static(self._format_branch_text(), classes="branch")
            if self.lines_added:
                yield Static(f"+{self.lines_added}", classes="additions")
            if self.lines_removed:
                yield Static(f"-{self.lines_removed}", classes="deletions")
        note_input = NoteInput(
            self.note,
            soft_wrap=True,
            compact=True,
            read_only=True,
            show_cursor=False,
            show_line_numbers=False,
            tab_behavior="focus",
            classes="note-input",
            id=f"note-input-{self.session_name}",
        )
        if not self.note:
            note_input.display = False
        yield note_input
        yield Static(tail, classes="line4")

    def _toggle_flash(self) -> None:
        """Toggle the blocker-alert-flash CSS class for the flash animation."""
        self.toggle_class("blocker-alert-flash")

    def _update_flash(self) -> None:
        """Start or stop the flash timer based on current + blocker alert state."""
        should_flash = self.is_current and self.has_blocker_alert
        if should_flash and self._flash_timer is None:
            self._flash_timer = self.set_interval(0.5, self._toggle_flash)
        elif not should_flash and self._flash_timer is not None:
            self._flash_timer.stop()
            self._flash_timer = None
            self.remove_class("blocker-alert-flash")

    def _update_breathing(self) -> None:
        """Start or stop the breathing dot timer based on active status."""
        should_breathe = self.status == "active"
        if should_breathe and self._breath_timer is None:
            self._breath_timer = self.set_interval(
                self._BREATH_INTERVAL, self._advance_breath
            )
        elif not should_breathe and self._breath_timer is not None:
            self._breath_timer.stop()
            self._breath_timer = None
            self._breath_frame = 0
            try:
                self.query_one(".name", Static).update(self._format_name_text())
            except Exception:
                pass  # widget not yet mounted

    def _advance_breath(self) -> None:
        """Advance the breathing animation by one frame."""
        self._breath_frame = (self._breath_frame + 1) % len(self._BREATH_COLORS)
        try:
            self.query_one(".name", Static).update(self._format_name_text())
        except Exception:
            pass  # widget not yet mounted

    def _apply_blocker_alert_class(self, has_blocker_alert: bool) -> None:
        """Add/remove the blocker-alert CSS class for the row red background."""
        if has_blocker_alert:
            self.add_class("blocker-alert")
        else:
            self.remove_class("blocker-alert")

    def update_state(
        self, is_active: bool, is_current: bool,
        status: str, has_blocker_alert: bool,
        branch: str | None = None, short_sha: str = "",
        lines_added: int = 0, lines_removed: int = 0,
        note: str = "",
    ) -> None:
        """Update mutable display state without rebuilding the widget."""
        if is_active != self.is_active:
            self.is_active = is_active
        if is_current != self.is_current:
            self.is_current = is_current
            if is_current:
                self.add_class("current")
            else:
                self.remove_class("current")
        if status != self.status:
            self.status = status
            self._update_breathing()
            self.query_one(".name", Static).update(self._format_name_text())
        if has_blocker_alert != self.has_blocker_alert:
            self.has_blocker_alert = has_blocker_alert
            self._apply_blocker_alert_class(has_blocker_alert)
        if (branch != self.branch or short_sha != self.short_sha
                or lines_added != self.lines_added or lines_removed != self.lines_removed):
            self.branch = branch
            self.short_sha = short_sha
            self.lines_added = lines_added
            self.lines_removed = lines_removed
            self.query_one(".branch", Static).update(self._format_branch_text())
            # Update additions widget
            additions = self.query(".additions")
            if self.lines_added:
                if additions:
                    additions.first().update(f"+{self.lines_added}")
                else:
                    line3 = self.query_one(".line3", Horizontal)
                    line3.mount(Static(f"+{self.lines_added}", classes="additions"))
            elif additions:
                additions.first().remove()
            # Update deletions widget
            deletions = self.query(".deletions")
            if self.lines_removed:
                if deletions:
                    deletions.first().update(f"-{self.lines_removed}")
                else:
                    line3 = self.query_one(".line3", Horizontal)
                    line3.mount(Static(f"-{self.lines_removed}", classes="deletions"))
            elif deletions:
                deletions.first().remove()
        if note != self.note and not self._editing:
            self.note = note
            try:
                ni = self.query_one(f"#note-input-{self.session_name}", NoteInput)
                ni.load_text(note)
                ni.display = bool(note)
            except Exception:
                pass
        self._update_flash()

    async def on_click(self) -> None:
        """Handle click: single-click selects, double-click edits note."""
        now = time.monotonic()
        elapsed = now - self._last_click_time
        self._last_click_time = now
        if elapsed < 0.4:
            if self._editing:
                self.save_and_close_editor()
            else:
                self._enter_edit_mode()
        elif not self._editing:
            self.post_message(self.Selected(self.session_name, self.session_id))

    def _enter_edit_mode(self) -> None:
        """Enable editing on the always-mounted NoteInput."""
        self._editing = True
        try:
            note_input = self.query_one(f"#note-input-{self.session_name}", NoteInput)
        except Exception:
            self._editing = False
            return
        note_input.display = True
        note_input.read_only = False
        note_input.show_cursor = True
        note_input.add_class("editing")
        note_input.focus()
        self._edit_timeout_timer = self.set_timer(60, self._on_edit_timeout)

    def _on_edit_timeout(self) -> None:
        """Auto-save after 60 seconds of inactivity."""
        self._edit_timeout_timer = None
        self.save_and_close_editor()

    def _exit_edit_mode(self, new_note: str | None = None) -> None:
        """Switch the NoteInput back to read-only display mode."""
        self._editing = False
        if self._edit_timeout_timer is not None:
            self._edit_timeout_timer.stop()
            self._edit_timeout_timer = None
        if new_note is not None:
            self.note = new_note
        try:
            note_input = self.query_one(f"#note-input-{self.session_name}", NoteInput)
        except Exception:
            return
        note_input.read_only = True
        note_input.show_cursor = False
        note_input.remove_class("editing")
        note_input.load_text(self.note)
        note_input.display = bool(self.note)

    def save_and_close_editor(self) -> None:
        """Save the current note and close the editor (used when clicking away)."""
        if not self._editing:
            return
        try:
            note_input = self.query_one(f"#note-input-{self.session_name}", NoteInput)
            new_note = note_input.text.strip()
        except Exception:
            new_note = self.note
        self.post_message(self.NoteEdited(self.session_name, new_note))
        self._exit_edit_mode(new_note)

    def on_note_input_submitted(self, event: NoteInput.Submitted) -> None:
        """Save the note on Enter."""
        if not self._editing:
            return
        new_note = event.value.strip()
        self.post_message(self.NoteEdited(self.session_name, new_note))
        self._exit_edit_mode(new_note)

    def key_escape(self) -> None:
        """Discard changes on Escape."""
        if self._editing:
            self._exit_edit_mode()
