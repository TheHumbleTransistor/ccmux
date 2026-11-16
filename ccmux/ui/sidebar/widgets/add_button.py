"""AddButton — "Add +" bar that slides up from the bottom of the sidebar."""

from textual import events
from textual.message import Message
from textual.widgets import Static

from ccmux.ui.sidebar.widgets.offsets import cells_offset

LABEL = "Add +"
HEIGHT = 3
SLIDE_DURATION = 0.2  # seconds for the bar to slide in or out


class AddButton(Static):
    """Gold "Add +" bar docked to the bottom of the sidebar, hidden until revealed."""

    class Clicked(Message):
        """Posted when the bar is clicked."""

    def __init__(self, **kwargs) -> None:
        super().__init__(LABEL, id="add-button", **kwargs)
        self.shown = False
        self.styles.offset = (0, HEIGHT)

    def show(self) -> None:
        if not self.shown:
            self.shown = True
            self.styles.animate("offset", value=cells_offset(0, 0), duration=SLIDE_DURATION)

    def hide(self) -> None:
        if self.shown:
            self.shown = False
            self.styles.animate("offset", value=cells_offset(0, HEIGHT), duration=SLIDE_DURATION)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Clicked())
