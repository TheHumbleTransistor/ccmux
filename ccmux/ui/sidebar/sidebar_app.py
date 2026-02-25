"""Sidebar application controller — Textual app, polling, signals."""

import asyncio
import logging
import os
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.geometry import Size
from textual.widgets import Static

from ccmux import state
from ccmux.naming import INNER_SESSION
from ccmux.ui.sidebar import snapshot
from ccmux.ui.sidebar.snapshot import DerivedSessionState, SessionSnapshot
from ccmux.ui.sidebar.widgets import SessionRow, RepoSessionsList, TitleBanner, AboutPanel

POLL_INTERVAL = 5.0
DEMO_POLL_INTERVAL = 1.0
POST_SELECTION_ACTIVITY_DEBOUNCE = 0.5  # seconds to ignore misleading activity caused by returning focus to the Claude Code window

# --- Logging ---
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
    BINDINGS = [("escape", "close_about", "Close about panel")]

    def __init__(
        self,
        snapshot_fn: Callable[[], Awaitable[list[SessionSnapshot]]] | None = None,
        poll_interval: float = POLL_INTERVAL,
        on_select: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._snapshot_fn = snapshot_fn
        self._poll_interval = poll_interval
        self._on_select = on_select
        self._last_derived: list[DerivedSessionState] | None = None
        self._blocked_sessions: set[str] = set()
        self._blocker_alerted_sessions: set[str] = set()
        self._post_selection_debounce: dict[str, float] = {}
        self._refresh_lock = asyncio.Lock()
        self._session_list: Vertical | None = None
        self._about_visible = False

    def compose(self) -> ComposeResult:
        yield TitleBanner()
        self._session_list = Vertical(id="instance-list")
        yield self._session_list
        yield AboutPanel(id="about-panel")

    async def on_mount(self) -> None:
        self._fix_nested_tmux_resize()
        await self._refresh_sessions(caller="mount")
        self.set_interval(self._poll_interval, self._poll_refresh)
        self._register_signal_handler()


    def _toggle_about(self) -> None:
        """Toggle between the session list and the about panel."""
        self._about_visible = not self._about_visible
        self.query_one("#about-panel").display = self._about_visible
        self.query_one("#instance-list").display = not self._about_visible

    def _close_about(self) -> None:
        """Close the about panel if it is currently visible."""
        if self._about_visible:
            self._toggle_about()

    def on_title_banner_clicked(self) -> None:
        """Handle title banner click by toggling the about panel."""
        self._toggle_about()

    def on_about_panel_closed(self) -> None:
        """Handle back button click in the about panel."""
        self._close_about()

    def action_close_about(self) -> None:
        """Close the about panel via Escape key."""
        self._close_about()

    def _fix_nested_tmux_resize(self) -> None:
        """Work around Textual resize being broken inside nested tmux.

        Root cause: Textual negotiates "in-band window resize" (xterm mode
        2048) at startup.  When active, Textual's SIGWINCH handler becomes a
        no-op — it expects the terminal to deliver resize dimensions via
        escape sequences (``\\x1b[48;H;W;PH;PWt``) instead.

        tmux 3.4+ advertises mode 2048 support, so Textual enables it.  But
        in ccmux's nested-tmux topology (sidebar pane → outer session →
        inner/bash sessions via ``TMUX= tmux attach``), the in-band resize
        escape sequences are either not forwarded or contain stale dimensions.
        The result: SIGWINCH arrives and the pty has the correct new size, but
        Textual never learns about it.

        Fix: fully disable mode 2048 and replace Textual's SIGWINCH handler
        with one that reads ``os.get_terminal_size()`` directly and posts the
        Resize event to Textual's event loop — the same thing Textual's own
        handler does, minus the broken in-band guard.
        """
        from textual.messages import InBandWindowResize

        driver = getattr(self, "_driver", None)
        if driver is not None:
            # Disable in-band resize now.
            driver._in_band_window_resize = False
            try:
                # Defer the disable sequence until after the first paint so it
                # doesn't interleave with Textual's initial screen output.
                self.call_after_refresh(lambda: driver.write("\x1b[?2048l"))
            except Exception:
                pass

            # Textual queries mode 2048 during start_application_mode() and
            # the DECRPM response arrives asynchronously.  When it does,
            # process_message() re-enables in-band resize — undoing our fix.
            # Intercept process_message to suppress InBandWindowResize so the
            # flag stays False permanently.
            _orig_process = driver.process_message

            def _process_no_ibwr(message):
                if isinstance(message, InBandWindowResize):
                    return
                _orig_process(message)

            driver.process_message = _process_no_ibwr

        # Replace Textual's SIGWINCH handler with one that always reads the
        # real pty size.  We capture the app and event loop references here
        # because the handler runs in a signal context (not async).
        _app = self
        _loop = asyncio.get_running_loop()

        def _on_sigwinch(signum, frame):
            try:
                pty = os.get_terminal_size()
                size = Size(pty.columns, pty.lines)
                asyncio.run_coroutine_threadsafe(
                    _app._post_message(events.Resize(size, size)),
                    loop=_loop,
                )
            except (OSError, RuntimeError):
                pass

        signal.signal(signal.SIGWINCH, _on_sigwinch)

        # Post an initial Resize with the real pane size.  The pane may have
        # been split before on_mount ran, and those SIGWINCHs were lost to
        # Textual's (now-disabled) in-band handler.  This catches up.
        try:
            pty = os.get_terminal_size()
            size = Size(pty.columns, pty.lines)
            self.post_message(events.Resize(size, size))
        except OSError:
            pass

    def _compute_session_state(
        self, entry: SessionSnapshot,
    ) -> tuple[str, bool]:
        """Compute derived (status, has_blocker_alert) from raw snapshot + sticky state."""
        name = entry.session_name
        raw_alert = entry.alert_state

        if not entry.is_active:
            # Deactivated — clear all sticky state
            self._blocked_sessions.discard(name)
            self._blocker_alerted_sessions.discard(name)
            return ("deactivated", False)

        if raw_alert == "bell":
            self._blocked_sessions.add(name)
            self._blocker_alerted_sessions.add(name)
        elif raw_alert == "activity":
            # If we recently clicked this row, ignore misleading activity
            # caused by returning focus to the Claude Code window.
            debounce_ts = self._post_selection_debounce.get(name)
            if debounce_ts is not None:
                if entry.activity_ts < debounce_ts + POST_SELECTION_ACTIVITY_DEBOUNCE:
                    raw_alert = None
                else:
                    del self._post_selection_debounce[name]
            if raw_alert == "activity":
                self._blocked_sessions.discard(name)
                self._blocker_alerted_sessions.discard(name)
        # raw_alert is None → sticky state persists (key for blocked persistence)

        if raw_alert == "activity":
            status = "active"
        elif name in self._blocked_sessions:
            status = "blocked"
        else:
            status = "idle"

        has_blocker_alert = name in self._blocker_alerted_sessions
        return (status, has_blocker_alert)

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

            # Compute derived state for each entry
            derived = [
                DerivedSessionState(
                    snapshot=entry,
                    status=computed[0],
                    has_blocker_alert=computed[1],
                )
                for entry in snap
                for computed in [self._compute_session_state(entry)]
            ]

            if derived == self._last_derived:
                log.debug("refresh SKIP (no change) caller=%s", caller)
                return

            old_derived = self._last_derived
            self._last_derived = derived

            if self._try_incremental_update(old_derived, derived):
                log.debug("refresh INCREMENTAL caller=%s", caller)
                return

            log.debug("refresh REBUILD caller=%s", caller)
            container = self._session_list
            if not derived:
                new_widgets = [Static("  No sessions")]
            else:
                grouped = snapshot.group_by_repo(derived)
                new_widgets = [
                    RepoSessionsList(repo_name, entries, id=f"repo-group-{repo_name}")
                    for repo_name, entries in grouped.items()
                ]
            await container.remove_children()
            await container.mount(*new_widgets)

    def _try_incremental_update(
        self,
        old_derived: list[DerivedSessionState] | None,
        new_derived: list[DerivedSessionState],
    ) -> bool:
        """Update session rows in place if structure is unchanged. Return True on success."""
        if not old_derived or not new_derived:
            return False
        # Structure check: same (repo, name) pairs in same order
        if [
            (d.snapshot.repo_name, d.snapshot.session_name) for d in old_derived
        ] != [
            (d.snapshot.repo_name, d.snapshot.session_name) for d in new_derived
        ]:
            return False
        for old_d, new_d in zip(old_derived, new_derived):
            if old_d != new_d:
                entry = new_d.snapshot
                row = self.query_one(f"#sess-{entry.session_name}", SessionRow)
                row.update_state(
                    entry.is_active, entry.is_current,
                    new_d.status, new_d.has_blocker_alert,
                    entry.branch, entry.short_sha,
                    entry.lines_added, entry.lines_removed,
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
        """Switch to the clicked session's tmux window and clear blocker alert."""
        # Record debounce timestamp so that misleading tmux activity from
        # returning focus to the Claude Code window doesn't change session status.
        self._post_selection_debounce[message.session_name] = time.time()

        # Clear blocker alert (row background) but keep blocked status (red circle)
        self._blocker_alerted_sessions.discard(message.session_name)
        try:
            row = self.query_one(f"#sess-{message.session_name}", SessionRow)
            if row.has_blocker_alert:
                row.update_state(
                    row.is_active, row.is_current,
                    row.status, False,
                    row.branch, row.short_sha,
                    row.lines_added, row.lines_removed,
                )
        except Exception:
            pass

        if self._on_select is not None:
            self._on_select(message.session_name)
            await self._refresh_sessions(caller="select")
            return

        # Look up window ID from state for precise targeting; fall back to name.
        sess = await asyncio.to_thread(state.get_session, message.session_name)
        cc_window_id = sess.tmux_cc_window_id if sess else None
        if cc_window_id:
            target = cc_window_id
        else:
            target = f"{INNER_SESSION}:{message.session_name}"
        name_target = f"{INNER_SESSION}:{message.session_name}"

        # Try switching directly first — works when the window still exists.
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["tmux", "select-window", "-t", target],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Window doesn't exist — auto-activate then retry.
            log.debug("select-window failed, auto-activating %s", message.session_name)
            try:
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
                # Retry select-window after activation (use name — activate creates a new window)
                await asyncio.to_thread(
                    subprocess.run,
                    ["tmux", "select-window", "-t", name_target],
                    check=True,
                    capture_output=True,
                )
            except Exception:
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
