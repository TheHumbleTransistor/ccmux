"""AddButton — bottom-docked "+" line for creating a session."""

from textual.message import Message
from textual.widgets import Static

PLUS = "\u254b"


class AddButton(Static):
    """Clickable "+" banner docked to the bottom of the sidebar."""

    class Clicked(Message):
        """Posted when the banner is clicked."""

    def __init__(self, **kwargs) -> None:
        super().__init__(PLUS, id="add-button", **kwargs)

    def on_click(self) -> None:
        self.post_message(self.Clicked())
