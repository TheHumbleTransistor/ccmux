"""RepoSessionsList — a collapsible, selectable repo group: header plus session rows."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar.snapshot import DerivedSessionState, aggregate_status
from ccmux.ui.sidebar.widgets.repo_header import RepoHeader
from ccmux.ui.sidebar.widgets.session_row import BREATH_COLORS, BREATH_INTERVAL, SessionRow

SELECTION_BLINK_INTERVAL = 0.5  # seconds per phase of the selected-header blink


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
        self._breath_timer = None
        self._breath_frame = 0
        self._breath_offset = hash(repo_path) % len(BREATH_COLORS)
        self._blink_timer = None
        self.set_class(collapsed, "collapsed")
        self.set_class(selected, "selected")

    @property
    def selected(self) -> bool:
        return self.has_class("selected")

    def _statuses(self) -> list[str]:
        rows = list(self.query(SessionRow))
        if rows:
            return [row.status for row in rows]
        return [derived.status for derived in self.sessions]

    def _status_indicator(self) -> str:
        status = aggregate_status(self._statuses())
        if status == "blocked":
            return "[#d70000]\u25cf[/]"
        if status == "active":
            color = BREATH_COLORS[(self._breath_frame + self._breath_offset) % len(BREATH_COLORS)]
            return f"[{color}]\u25cf[/]"
        if status == "deactivated":
            return "[#9e9e9e]\u25cb[/]"
        return "[#9e9e9e]\u25cf[/]"

    def _toggle_text(self) -> str:
        return "\u25b8" if self.collapsed else "\u25be"

    def _title_text(self) -> str:
        if not self.collapsed:
            return self.repo_name
        return (
            f"{self._status_indicator()} {self.repo_name} "
            f"[#666666 not bold]({len(self.sessions)})[/]"
        )

    def compose(self) -> ComposeResult:
        yield RepoHeader(self.repo_path, self._toggle_text(), self._title_text())
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

    def on_mount(self) -> None:
        self._update_breathing()
        self._update_selection_blink()

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "selected")
        self._update_selection_blink()

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the session rows and update the header to match."""
        self.collapsed = collapsed
        self.set_class(collapsed, "collapsed")
        for row in self.query(SessionRow):
            row.display = not collapsed
        self.refresh_header()

    def refresh_header(self) -> None:
        """Sync the header arrow, title, status dot, and alert highlight with the row states."""
        self._update_breathing()
        self.query_one(RepoHeader).update(self._toggle_text(), self._title_text())
        alert = self.collapsed and any(row.has_blocker_alert for row in self.query(SessionRow))
        self.set_class(alert, "blocker-alert")

    def _update_selection_blink(self) -> None:
        if self.selected and self._blink_timer is None:
            self._blink_timer = self.set_interval(SELECTION_BLINK_INTERVAL, self._toggle_blink)
        elif not self.selected and self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None
            self.remove_class("selected-flash")

    def _toggle_blink(self) -> None:
        self.toggle_class("selected-flash")

    def _update_breathing(self) -> None:
        should_breathe = self.collapsed and aggregate_status(self._statuses()) == "active"
        if should_breathe and self._breath_timer is None:
            self._breath_timer = self.set_interval(BREATH_INTERVAL, self._advance_breath)
        elif not should_breathe and self._breath_timer is not None:
            self._breath_timer.stop()
            self._breath_timer = None
            self._breath_frame = 0

    def _advance_breath(self) -> None:
        self._breath_frame = (self._breath_frame + 1) % len(BREATH_COLORS)
        self.query_one(RepoHeader).update(self._toggle_text(), self._title_text())
