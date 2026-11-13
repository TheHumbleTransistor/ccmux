"""AddButton — bottom-docked "+ new session" button."""

from textual.message import Message
from textual.widgets import Static


class AddButton(Static):
    """Clickable "+ new session" line docked to the bottom of the sidebar."""

    class Clicked(Message):
        """Posted when the button is clicked."""

    def __init__(self, **kwargs) -> None:
        super().__init__("+ new session", id="add-button", **kwargs)

    def on_click(self) -> None:
        self.post_message(self.Clicked())
