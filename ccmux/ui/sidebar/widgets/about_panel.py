"""AboutPanel — info/about panel widget for the sidebar."""

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from ccmux import __version__

ABOUT_TEXT = f"""\
[bold #d7af5f]ccmux[/] [dim]v{__version__}[/]

Made by [bold #bcbcbc]The Humble Transistor[/]
Embedded electronics development
[dim]TheHumbleTransistor.com[/]

[dim]github.com/TheHumbleTransistor/ccmux[/]
"""


class AboutPanel(Vertical):
    """Info/about panel shown when the title banner is clicked."""

    class Closed(Message):
        """Posted when the back button is clicked."""

    class _BackButton(Static):
        def on_click(self) -> None:
            self.post_message(AboutPanel.Closed())

    def compose(self):
        yield self._BackButton("[#666666]\u2190 back[/]", id="about-back")
        yield Static(ABOUT_TEXT, id="about-content")
