"""InstanceRow — three-line widget with tree characters, indicator, name, and type."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static


class InstanceRow(Vertical):
    """A clickable 3-line row showing tree hierarchy, instance status, name, and type."""

    class Selected(Message):
        """Posted when the user clicks an instance row."""

        def __init__(self, instance_name: str, session: str) -> None:
            super().__init__()
            self.instance_name = instance_name
            self.session = session

    def __init__(
        self,
        instance_name: str,
        instance_type: str,
        is_active: bool,
        is_current: bool,
        session: str,
        alert_state: str | None = None,
        is_last: bool = False,
        branch: str | None = None,
        short_sha: str = "",
        lines_added: int = 0,
        lines_removed: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.instance_name = instance_name
        self.instance_type = instance_type
        self.is_active = is_active
        self.is_current = is_current
        self.session = session
        self.alert_state = alert_state
        self.is_last = is_last
        self.branch = branch
        self.short_sha = short_sha
        self.lines_added = lines_added
        self.lines_removed = lines_removed
        self._flash_timer = None
        if is_current:
            self.add_class("current")
        self._apply_alert_class(alert_state)
        self._update_flash()

    def _tree_chars(self) -> tuple[str, str, str]:
        """Return (top, branch, tail) tree characters."""
        if self.is_last:
            return ("│", "└── ", "")
        return ("│", "├── ", "│")

    def _format_git_line(self) -> str:
        """Build the line3 content with tree prefix, branch/sha, and diff stats."""
        prefix = "│     " if not self.is_last else "      "

        # Determine what to display: branch name, or (sha) if detached
        if self.branch is not None:
            ref_text = self.branch
        elif self.short_sha:
            ref_text = f"({self.short_sha})"
        else:
            return prefix.rstrip()

        stats = ""
        if self.lines_added or self.lines_removed:
            parts = []
            if self.lines_added:
                parts.append(f"[green]+{self.lines_added}[/green]")
            if self.lines_removed:
                parts.append(f"[red]-{self.lines_removed}[/red]")
            stats = " " + " ".join(parts)

        # Truncate ref to fit: sidebar is ~39 usable chars, prefix is 6, stats need space
        stats_plain_len = 0
        if self.lines_added:
            stats_plain_len += len(f"+{self.lines_added}") + 1
        if self.lines_removed:
            stats_plain_len += len(f"-{self.lines_removed}") + 1
        max_ref = 39 - len(prefix) - stats_plain_len
        ref_display = ref_text[:max_ref] if max_ref > 0 else ""

        return f"{prefix}{ref_display}{stats}"

    def compose(self) -> ComposeResult:
        indicator = "\u25cf" if self.is_active else "\u25cb"
        top, branch, tail = self._tree_chars()
        yield Static(top, classes="line1")
        with Horizontal(classes="line2"):
            yield Static(f"{branch}{indicator} {self.instance_name}", classes="name")
            yield Static(self.instance_type, classes="type")
        git_line = self._format_git_line()
        yield Static(git_line, classes="line3", markup=True)

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
            indicator = "●" if is_active else "○"
            tree_branch = self._tree_chars()[1]
            self.query_one(".name", Static).update(
                f"{tree_branch}{indicator} {self.instance_name}"
            )
        if is_current != self.is_current:
            self.is_current = is_current
            if is_current:
                self.add_class("current")
            else:
                self.remove_class("current")
        if alert_state != self.alert_state:
            self.alert_state = alert_state
            self._apply_alert_class(alert_state)
        if (branch != self.branch or short_sha != self.short_sha
                or lines_added != self.lines_added or lines_removed != self.lines_removed):
            self.branch = branch
            self.short_sha = short_sha
            self.lines_added = lines_added
            self.lines_removed = lines_removed
            self.query_one(".line3", Static).update(self._format_git_line())
        self._update_flash()

    async def on_click(self) -> None:
        """Signal that this instance row was clicked."""
        self.post_message(self.Selected(self.instance_name, self.session))
