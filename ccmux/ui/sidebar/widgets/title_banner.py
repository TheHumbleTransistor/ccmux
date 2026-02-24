"""TitleBanner — ASCII art logo widget for the sidebar header."""

from textual.widgets import Static

LOGO = (
    "                                     \n"
    "                                     \n"
    "▄█████ ▄█████ ██▄  ▄██ ██  ██ ██  ██ \n"
    "██     ██     ██ ▀▀ ██ ██  ██  ████  \n"
    "▀█████ ▀█████ ██    ██ ▀████▀ ██  ██ \n"
    "                                     "
)


class TitleBanner(Static):
    """Non-interactive ASCII art banner for the sidebar header."""

    def __init__(self, **kwargs) -> None:
        super().__init__(LOGO, id="title", **kwargs)
