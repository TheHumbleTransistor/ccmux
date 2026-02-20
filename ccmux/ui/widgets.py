"""Sidebar widget classes."""

import asyncio
import subprocess

from textual import events
from textual.widgets import Static


class NonInteractiveStatic(Static):
    """Static widget that consumes click events to prevent propagation."""

    def on_click(self, event: events.Click) -> None:
        event.stop()


class InstanceRow(Static):
    """A clickable 3-row block: tree pad above, content, tree pad below."""

    def __init__(
        self,
        instance_name: str,
        instance_type: str,
        is_active: bool,
        is_current: bool,
        is_last: bool,
        session: str,
        alert_state: str | None = None,
        **kwargs,
    ) -> None:
        self.instance_name = instance_name
        self.instance_type = instance_type
        self.is_active = is_active
        self.is_current = is_current
        self.is_last = is_last
        self.session = session
        self.alert_state = alert_state
        super().__init__(self._render_label(), **kwargs)
        if is_current:
            self.add_class("current")
        self._apply_alert_class(alert_state)

    def _render_label(self) -> str:
        connector = "\u2514\u2500\u2500" if self.is_last else "\u251c\u2500\u2500"
        indicator = "\u25cf" if self.is_active else "\u25cb"
        content = f"{connector} {indicator} {self.instance_name:<10} {self.instance_type}"
        bottom = "" if self.is_last else "\u2502"
        return f"\u2502\n{content}\n{bottom}"

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
        self, is_active: bool, is_current: bool, is_last: bool, alert_state: str | None = None
    ) -> None:
        """Update this row's display without remounting."""
        self.is_active = is_active
        self.is_current = is_current
        self.is_last = is_last
        self.alert_state = alert_state
        self.update(self._render_label())
        if is_current:
            self.add_class("current")
        else:
            self.remove_class("current")
        self._apply_alert_class(alert_state)

    async def on_click(self) -> None:
        """Switch to this instance's tmux window."""
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["tmux", "select-window", "-t", f"{self.session}-inner:{self.instance_name}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass


class RepoHeader(NonInteractiveStatic):
    """Non-clickable section header for a repository group."""
