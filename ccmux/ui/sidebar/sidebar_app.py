"""Sidebar application controller — Textual app, polling, signals."""

import asyncio
import logging
import os
import signal
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.geometry import Size
from textual.widgets import Static

from ccmux.naming import INNER_SESSION
from ccmux.ui.sidebar import snapshot
from ccmux.ui.sidebar.snapshot import SessionSnapshot
from ccmux.ui.sidebar.widgets import SessionRow, RepoSessionsList, TitleBanner, AboutPanel

POLL_INTERVAL = 5.0
DEMO_POLL_INTERVAL = 1.0

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
        self._last_snapshot: list[SessionSnapshot] | None = None
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
        # Clear bell styling on the widget for instant feedback (all modes)
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

        if self._on_select is not None:
            self._on_select(message.session_name)
            await self._refresh_sessions(caller="select")
            return

        # Use window ID when available for precise targeting; fall back to name.
        if message.tmux_cc_window_id:
            target = message.tmux_cc_window_id
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
