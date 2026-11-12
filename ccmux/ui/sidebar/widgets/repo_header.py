"""RepoHeader — clickable section header for a repository group."""

from textual.message import Message
from textual.widgets import Static


class RepoHeader(Static):
    """Clickable section header for a repository group."""

    class Clicked(Message):
        """Posted when the user clicks a repo group header."""

        def __init__(self, repo_path: str) -> None:
            super().__init__()
            self.repo_path = repo_path

    def __init__(self, *args, repo_path: str = "", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.repo_path = repo_path

    def on_click(self) -> None:
        self.post_message(self.Clicked(self.repo_path))
