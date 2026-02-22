"""RepoInstancesList — compound widget replacing view.py loop + spacer widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar.snapshot import InstanceSnapshot
from ccmux.ui.sidebar.widgets.repo_header import RepoHeader
from ccmux.ui.sidebar.widgets.instance_row import InstanceRow


class RepoInstancesList(Vertical):
    """A repo group: header followed by instance rows."""

    def __init__(
        self,
        repo_name: str,
        instances: list[InstanceSnapshot],
        session_name: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_name = repo_name
        self.instances = instances
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        yield RepoHeader(f"\u25cf {self.repo_name}/")
        last_idx = len(self.instances) - 1
        for i, entry in enumerate(self.instances):
            yield InstanceRow(
                entry.instance_name, entry.instance_type,
                entry.is_active, entry.is_current,
                self.session_name, entry.alert_state,
                is_last=(i == last_idx),
                branch=entry.branch,
                short_sha=entry.short_sha,
                lines_added=entry.lines_added,
                lines_removed=entry.lines_removed,
                id=f"inst-{entry.instance_name}",
            )
