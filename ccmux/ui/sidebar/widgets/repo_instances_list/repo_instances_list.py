"""RepoInstancesList — compound widget replacing view.py loop + spacer widgets."""

from textual.app import ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar.widgets.repo_header import RepoHeader
from ccmux.ui.sidebar.widgets.instance_row import InstanceRow


class RepoInstancesList(Vertical):
    """A repo group: header followed by instance rows."""

    CSS_PATH = "repo_instances_list.tcss"

    def __init__(
        self,
        repo_name: str,
        instances: list[tuple],
        session_name: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_name = repo_name
        self.instances = instances
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        yield RepoHeader(f"\u25cf {self.repo_name}/")
        for _, name, type_, active, current, alert in self.instances:
            yield InstanceRow(name, type_, active, current, self.session_name, alert, id=f"inst-{name}")
