"""RepoSessionsList — compound widget replacing view.py loop + spacer widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar.snapshot import SessionSnapshot
from ccmux.ui.sidebar.widgets.repo_header import RepoHeader
from ccmux.ui.sidebar.widgets.session_row import SessionRow


class RepoSessionsList(Vertical):
    """A repo group: header followed by session rows."""

    def __init__(
        self,
        repo_name: str,
        sessions: list[SessionSnapshot],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_name = repo_name
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        yield RepoHeader(f"\u25cf {self.repo_name}/")
        last_idx = len(self.sessions) - 1
        for i, entry in enumerate(self.sessions):
            yield SessionRow(
                entry.session_name, entry.session_type,
                entry.is_active, entry.is_current,
                entry.alert_state,
                is_last=(i == last_idx),
                branch=entry.branch,
                short_sha=entry.short_sha,
                lines_added=entry.lines_added,
                lines_removed=entry.lines_removed,
                tmux_cc_window_id=entry.tmux_cc_window_id,
                id=f"sess-{entry.session_name}",
            )
