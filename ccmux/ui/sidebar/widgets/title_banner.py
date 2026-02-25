"""TitleBanner — ASCII art logo widget for the sidebar header."""

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

LOGO = (
    "\u2584\u2588\u2588\u2588\u2588\u2588 \u2584\u2588\u2588\u2588\u2588\u2588 \u2588\u2588\u2584  \u2584\u2588\u2588 \u2588\u2588  \u2588\u2588 \u2588\u2588  \u2588\u2588 \n"
    "\u2588\u2588     \u2588\u2588     \u2588\u2588 \u2580\u2580 \u2588\u2588 \u2588\u2588  \u2588\u2588  \u2588\u2588\u2588\u2588  \n"
    "\u2580\u2588\u2588\u2588\u2588\u2588 \u2580\u2588\u2588\u2588\u2588\u2588 \u2588\u2588    \u2588\u2588 \u2580\u2588\u2588\u2588\u2588\u2580 \u2588\u2588  \u2588\u2588 \n"
    "                                     "
)


class TitleBanner(Vertical):
    """Clickable ASCII art banner for the sidebar header."""

    class Clicked(Message):
        """Posted when the title banner is clicked."""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="title", **kwargs)

    def compose(self):
        yield Static("\u24d8", id="title-info-icon")
        yield Static(LOGO, id="title-logo")

    def on_click(self) -> None:
        self.post_message(self.Clicked())
