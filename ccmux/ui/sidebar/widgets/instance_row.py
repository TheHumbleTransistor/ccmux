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

    def compose(self) -> ComposeResult:
        indicator = "\u25cf" if self.is_active else "\u25cb"
        top, branch, tail = self._tree_chars()
        yield Static(top, classes="line1")
        with Horizontal(classes="line2"):
            yield Static(f"{branch}{indicator} {self.instance_name}", classes="name")
            yield Static(self.instance_type, classes="type")
        yield Static(tail, classes="line3")

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

    def update_state(self, is_active: bool, is_current: bool, alert_state: str | None) -> None:
        """Update mutable display state without rebuilding the widget."""
        if is_active != self.is_active:
            self.is_active = is_active
            indicator = "●" if is_active else "○"
            branch = self._tree_chars()[1]
            self.query_one(".name", Static).update(
                f"{branch}{indicator} {self.instance_name}"
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
        self._update_flash()

    async def on_click(self) -> None:
        """Signal that this instance row was clicked."""
        self.post_message(self.Selected(self.instance_name, self.session))
