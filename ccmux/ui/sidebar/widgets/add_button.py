"""AddButton — bottom-docked "Add +" line for creating a session."""

from textual.message import Message
from textual.widgets import Static

LABEL = "Add +"


class AddButton(Static):
    """Clickable "Add +" line docked to the bottom of the sidebar."""

    class Clicked(Message):
        """Posted when the banner is clicked."""

    def __init__(self, **kwargs) -> None:
        super().__init__(LABEL, id="add-button", **kwargs)

    def on_click(self) -> None:
        self.post_message(self.Clicked())
