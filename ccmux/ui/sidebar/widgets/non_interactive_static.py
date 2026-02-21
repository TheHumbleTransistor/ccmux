"""Non-interactive static widget that consumes click events."""

from textual import events
from textual.widgets import Static


class NonInteractiveStatic(Static):
    """Static widget that consumes click events to prevent propagation."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
