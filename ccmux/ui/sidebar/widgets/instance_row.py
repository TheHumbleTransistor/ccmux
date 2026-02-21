"""InstanceRow — horizontal container with indicator, name, and type labels."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static


class InstanceRow(Horizontal):
    """A clickable row showing instance status, name, and type."""

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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.instance_name = instance_name
        self.instance_type = instance_type
        self.is_active = is_active
        self.is_current = is_current
        self.session = session
        self.alert_state = alert_state
        if is_current:
            self.add_class("current")
        self._apply_alert_class(alert_state)

    def compose(self) -> ComposeResult:
        indicator = "\u25cf" if self.is_active else "\u25cb"
        yield Static(indicator, classes="indicator")
        yield Static(self.instance_name, classes="name")
        yield Static(self.instance_type, classes="type")

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
            self.query_one(".indicator", Static).update("●" if is_active else "○")
        if is_current != self.is_current:
            self.is_current = is_current
            if is_current:
                self.add_class("current")
            else:
                self.remove_class("current")
        if alert_state != self.alert_state:
            self.alert_state = alert_state
            self._apply_alert_class(alert_state)

    async def on_click(self) -> None:
        """Signal that this instance row was clicked."""
        self.post_message(self.Selected(self.instance_name, self.session))
