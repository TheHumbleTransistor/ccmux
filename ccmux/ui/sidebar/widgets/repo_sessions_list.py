"""RepoSessionsList — compound widget replacing view.py loop + spacer widgets."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar.snapshot import DerivedSessionState
from ccmux.ui.sidebar.widgets.repo_header import RepoHeader
from ccmux.ui.sidebar.widgets.session_row import SessionRow


class RepoSessionsList(Vertical):
    """A repo group: header followed by session rows."""

    def __init__(
        self,
        repo_name: str,
        sessions: list[DerivedSessionState],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_name = repo_name
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        yield RepoHeader(f"\u25cf {self.repo_name}")
        last_idx = len(self.sessions) - 1
        for i, derived in enumerate(self.sessions):
            entry = derived.snapshot
            yield SessionRow(
                entry.session_name, entry.session_type,
                entry.is_active, entry.is_current,
                status=derived.status,
                has_blocker_alert=derived.has_blocker_alert,
                is_last=(i == last_idx),
                branch=entry.branch,
                short_sha=entry.short_sha,
                lines_added=entry.lines_added,
                lines_removed=entry.lines_removed,
                session_id=entry.session_id,
                note=entry.note,
                id=f"sess-{entry.session_name}",
            )
