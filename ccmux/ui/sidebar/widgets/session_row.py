"""SessionRow — four-line widget with tree characters, indicator, name, and git info."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static


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

    def __init__(
        self,
        session_name: str,
        session_type: str,
        is_active: bool,
        is_current: bool,
        alert_state: str | None = None,
        is_last: bool = False,
        branch: str | None = None,
        short_sha: str = "",
        lines_added: int = 0,
        lines_removed: int = 0,
        session_id: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session_name = session_name
        self.session_id = session_id
        self.session_type = session_type
        self.is_active = is_active
        self.is_current = is_current
        self.alert_state = alert_state
        self.is_last = is_last
        self.branch = branch
        self.short_sha = short_sha
        self.lines_added = lines_added
        self.lines_removed = lines_removed
        self._flash_timer = None
        self._breath_timer = None
        self._breath_frame = 0
        self._breath_offset = hash(session_name) % len(self._BREATH_COLORS)
        if is_current:
            self.add_class("current")
        self._apply_alert_class(alert_state)
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
        if not self.is_active:
            indicator = "\u25cb"  # ○
        elif self._breath_timer is not None:
            color = self._BREATH_COLORS[(self._breath_frame + self._breath_offset) % len(self._BREATH_COLORS)]
            indicator = f"[{color}]\u25cf[/]"
        else:
            indicator = "\u25cf"  # ● (inherits grey text color)
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
        yield Static(tail, classes="line4")

    def _toggle_flash(self) -> None:
        """Toggle the bell-flash CSS class for the flash animation."""
        self.toggle_class("bell-flash")

    def _update_flash(self) -> None:
        """Start or stop the flash timer based on current + bell state."""
        should_flash = self.is_current and self.alert_state == "bell"
        if should_flash and self._flash_timer is None:
            self._flash_timer = self.set_interval(0.5, self._toggle_flash)
        elif not should_flash and self._flash_timer is not None:
            self._flash_timer.stop()
            self._flash_timer = None
            self.remove_class("bell-flash")

    def _update_breathing(self) -> None:
        """Start or stop the breathing dot timer based on activity state."""
        should_breathe = self.alert_state == "activity"
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

    def _apply_alert_class(self, alert_state: str | None) -> None:
        """Add/remove bell and activity CSS classes based on alert state."""
        if alert_state == "bell":
            self.add_class("bell")
            self.remove_class("activity")
        elif alert_state == "activity":
            self.add_class("activity")
            self.remove_class("bell")
        else:
            self.remove_class("bell")
            self.remove_class("activity")

    def update_state(
        self, is_active: bool, is_current: bool, alert_state: str | None,
        branch: str | None = None, short_sha: str = "",
        lines_added: int = 0, lines_removed: int = 0,
    ) -> None:
        """Update mutable display state without rebuilding the widget."""
        if is_active != self.is_active:
            self.is_active = is_active
            self.query_one(".name", Static).update(self._format_name_text())
        if is_current != self.is_current:
            self.is_current = is_current
            if is_current:
                self.add_class("current")
            else:
                self.remove_class("current")
        if alert_state != self.alert_state:
            self.alert_state = alert_state
            self._apply_alert_class(alert_state)
            self._update_breathing()
            self.query_one(".name", Static).update(self._format_name_text())
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
        self._update_flash()

    async def on_click(self) -> None:
        """Signal that this session row was clicked."""
        self.post_message(self.Selected(self.session_name, self.session_id))
