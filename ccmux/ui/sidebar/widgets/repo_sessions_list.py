"""RepoSessionsList — a collapsible, selectable repo group: header plus session rows."""

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
        repo_path: str,
        repo_name: str,
        sessions: list[DerivedSessionState],
        collapsed: bool = False,
        selected: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self.repo_name = repo_name
        self.sessions = sessions
        self.collapsed = collapsed
        self.set_class(collapsed, "collapsed")
        self.set_class(selected, "selected")

    @property
    def selected(self) -> bool:
        return self.has_class("selected")

    def _header_text(self) -> str:
        if self.collapsed:
            return f"\u25b8 {self.repo_name} ({len(self.sessions)})"
        return f"\u25be {self.repo_name}"

    def compose(self) -> ComposeResult:
        yield RepoHeader(self._header_text(), repo_path=self.repo_path)
        last_idx = len(self.sessions) - 1
        for i, derived in enumerate(self.sessions):
            entry = derived.snapshot
            row = SessionRow(
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
                is_shallow=entry.is_shallow,
                id=f"sess-{entry.session_name}",
            )
            row.display = not self.collapsed
            yield row

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the session rows and update the header to match."""
        self.collapsed = collapsed
        self.set_class(collapsed, "collapsed")
        for row in self.query(SessionRow):
            row.display = not collapsed
        self.refresh_header()

    def refresh_header(self) -> None:
        """Sync the header text and alert highlight with the current row states."""
        self.query_one(RepoHeader).update(self._header_text())
        alert = self.collapsed and any(row.has_blocker_alert for row in self.query(SessionRow))
        self.set_class(alert, "blocker-alert")
