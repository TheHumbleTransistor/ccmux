"""RepoHeader — section header for a repository group: collapse arrow plus clickable title."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static


class RepoHeader(Horizontal):
    """Section header for a repository group: a collapse arrow and a clickable title."""

    class ToggleClicked(Message):
        """Posted when the user clicks the collapse arrow."""

        def __init__(self, repo_path: str) -> None:
            super().__init__()
            self.repo_path = repo_path

    class Clicked(Message):
        """Posted when the user clicks the title area."""

        def __init__(self, repo_path: str) -> None:
            super().__init__()
            self.repo_path = repo_path

    class _Toggle(Static):
        def on_click(self) -> None:
            self.post_message(RepoHeader.ToggleClicked(self.parent.repo_path))

    class _Title(Static):
        def on_click(self) -> None:
            self.post_message(RepoHeader.Clicked(self.parent.repo_path))

    def __init__(self, repo_path: str, toggle: str, title: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self._toggle_text = toggle
        self._title_text = title

    def compose(self) -> ComposeResult:
        yield self._Toggle(self._toggle_text, classes="toggle")
        yield self._Title(self._title_text, classes="title")

    def update(self, toggle: str, title: str) -> None:
        """Replace the arrow and title text."""
        self.query_one(".toggle", Static).update(toggle)
        self.query_one(".title", Static).update(title)
