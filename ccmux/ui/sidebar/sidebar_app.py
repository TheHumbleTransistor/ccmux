"""Sidebar application controller — Textual app, polling, signals."""

import asyncio
import logging
import signal
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ccmux.naming import INNER_SESSION
from ccmux.ui.sidebar import snapshot
from ccmux.ui.sidebar.snapshot import SessionSnapshot
from ccmux.ui.sidebar.widgets import SessionRow, RepoSessionsList

POLL_INTERVAL = 5.0
DEMO_POLL_INTERVAL = 1.0

# --- Diagnostic logging ---
_LOG_DIR = Path.home() / ".ccmux"
_LOG_FILE = _LOG_DIR / "sidebar_debug.log"


def _setup_logger() -> logging.Logger:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ccmux.sidebar")
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(_LOG_FILE, mode="a")
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    return logger


log = _setup_logger()


class SidebarApp(App):
    """Textual sidebar showing ccmux sessions for click-to-switch navigation."""

    CSS_PATH = "sidebar.tcss"
    ALLOW_SELECT = False

    def __init__(
        self,
        snapshot_fn: Callable[[], Awaitable[list[SessionSnapshot]]] | None = None,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        super().__init__()
        self._snapshot_fn = snapshot_fn
        self._poll_interval = poll_interval
        self._last_snapshot: list[SessionSnapshot] | None = None
        self._refresh_lock = asyncio.Lock()
        self._session_list: Vertical | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "                                     \n"
            "                                     \n"
            "▄█████ ▄█████ ██▄  ▄██ ██  ██ ██  ██ \n"
            "██     ██     ██ ▀▀ ██ ██  ██  ████  \n"
            "▀█████ ▀█████ ██    ██ ▀████▀ ██  ██ \n"
            "                                     ",
            id="title",
        )
        self._session_list = Vertical(id="instance-list")
        yield self._session_list

    async def on_resize(self, event: events.Resize) -> None:
        log.debug("on_resize size=%dx%d", event.size.width, event.size.height)

    async def on_mount(self) -> None:
        await self._refresh_sessions(caller="mount")
        self.set_interval(self._poll_interval, self._poll_refresh)
        self._register_signal_handler()

    async def _refresh_sessions(self, caller: str = "unknown") -> None:
        """Refresh the session list, using incremental updates when possible."""
        if self._session_list is None:
            return
        if self._refresh_lock.locked():
            log.debug("refresh SKIPPED (already running) caller=%s", caller)
            return
        async with self._refresh_lock:
            log.debug("refresh START caller=%s", caller)

            if self._snapshot_fn is not None:
                snap = await self._snapshot_fn()
            else:
                snap = await snapshot.build_snapshot()

            if snap == self._last_snapshot:
                log.debug("refresh SKIP (no change) caller=%s", caller)
                return

            old_snap = self._last_snapshot
            self._last_snapshot = snap

            if self._try_incremental_update(old_snap, snap):
                log.debug("refresh INCREMENTAL caller=%s", caller)
                return

            log.debug("refresh REBUILD caller=%s", caller)
            container = self._session_list
            if not snap:
                new_widgets = [Static("  No sessions")]
            else:
                grouped = snapshot.group_by_repo(snap)
                new_widgets = [
                    RepoSessionsList(repo_name, entries, id=f"repo-group-{repo_name}")
                    for repo_name, entries in grouped.items()
                ]
            await container.remove_children()
            await container.mount(*new_widgets)

    def _try_incremental_update(
        self, old_snap: list[SessionSnapshot] | None, new_snap: list[SessionSnapshot],
    ) -> bool:
        """Update session rows in place if structure is unchanged. Return True on success."""
        if not old_snap or not new_snap:
            return False
        # Structure check: same (repo, name) pairs in same order
        if [(e.repo_name, e.session_name) for e in old_snap] != [
            (e.repo_name, e.session_name) for e in new_snap
        ]:
            return False
        for old_entry, new_entry in zip(old_snap, new_snap):
            if old_entry != new_entry:
                row = self.query_one(f"#sess-{new_entry.session_name}", SessionRow)
                row.update_state(
                    new_entry.is_active, new_entry.is_current, new_entry.alert_state,
                    new_entry.branch, new_entry.short_sha,
                    new_entry.lines_added, new_entry.lines_removed,
                )
        return True

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        await self._refresh_sessions(caller="poll")

    def _register_signal_handler(self) -> None:
        """Register SIGUSR1 handler for instant refresh on state changes."""
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGUSR1, self._on_sigusr1)
        except (ValueError, OSError):
            pass

    def _on_sigusr1(self) -> None:
        """Handle SIGUSR1 signal by scheduling a refresh."""
        log.debug("SIGUSR1 received")
        self.run_worker(
            self._refresh_sessions(caller="signal"),
            group="refresh",
            exit_on_error=False,
        )

    async def on_session_row_selected(self, message: SessionRow.Selected) -> None:
        """Switch to the clicked session's tmux window and clear bell alert."""
        # Auto-reactivate deactivated sessions on click
        try:
            row = self.query_one(f"#sess-{message.session_name}", SessionRow)
            if not row.is_active:
                log.debug("auto-activating inactive session %s", message.session_name)
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["ccmux", "activate", "-y", message.session_name],
                    capture_output=True,
                )
                if result.returncode != 0:
                    log.error(
                        "auto-activate failed for %s: %s",
                        message.session_name,
                        result.stderr.decode(errors="replace").strip(),
                    )
                    return
        except Exception:
            pass

        target = f"{INNER_SESSION}:{message.session_name}"
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["tmux", "select-window", "-t", target],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        # Focus the Claude Code pane in the outer session
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["tmux", "select-pane", "-t", ":0.1"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        # Clear bell flag on the tmux window (needed when re-selecting the current window)
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["tmux", "set", "-w", "-t", target, "@ccmux_bell", "0"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        # Immediately clear bell styling on the widget for instant feedback
        try:
            row = self.query_one(f"#sess-{message.session_name}", SessionRow)
            if row.alert_state == "bell":
                row.update_state(
                    row.is_active, row.is_current, None,
                    row.branch, row.short_sha,
                    row.lines_added, row.lines_removed,
                )
        except Exception:
            pass
