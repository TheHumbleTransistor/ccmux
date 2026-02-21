"""Sidebar application controller — Textual app, polling, signals, entry point."""

import asyncio
import atexit
import logging
import signal
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar import model, view
from ccmux.ui.sidebar.process_id import remove_pid_file, write_pid_file
from ccmux.ui.sidebar.widgets import NonInteractiveStatic

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
    """Textual sidebar showing ccmux instances for click-to-switch navigation."""

    CSS_PATH = "sidebar.tcss"
    ALLOW_SELECT = False

    def __init__(self, session: str, demo: bool = False) -> None:
        super().__init__()
        self.session_name = session
        self._demo = demo
        self._demo_tick = 0
        self._last_snapshot: list[tuple] = []
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield NonInteractiveStatic("CCMUX", id="title")
        yield NonInteractiveStatic(f"Session: {self.session_name}", id="header")
        yield NonInteractiveStatic("", id="spacer")
        yield Vertical(id="instance-list")

    async def on_mount(self) -> None:
        await self._refresh_instances(caller="mount")
        interval = DEMO_POLL_INTERVAL if self._demo else POLL_INTERVAL
        self.set_interval(interval, self._poll_refresh)
        self._register_signal_handler()

    async def _refresh_instances(self, caller: str = "unknown") -> None:
        """Refresh the instance list with a full rebuild every time."""
        async with self._refresh_lock:
            log.debug("refresh START caller=%s", caller)

            snapshot = await model.build_snapshot(
                self.session_name, demo=self._demo, demo_tick=self._demo_tick
            )
            if self._demo:
                self._demo_tick += 1

            log.debug("refresh REBUILD caller=%s", caller)
            container = self.query_one("#instance-list", Vertical)
            new_widgets = view.build_widgets(snapshot, self.session_name)
            await container.remove_children()
            await container.mount(*new_widgets)

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        await self._refresh_instances(caller="poll")

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
            self._refresh_instances(caller="signal"), group="refresh",
        )


def main() -> None:
    """Entry point: python -m ccmux.ui.sidebar <session>"""
    if "--demo" in sys.argv:
        app = SidebarApp(session="demo", demo=True)
        app.run()
        return

    if len(sys.argv) < 2:
        print("Usage: python -m ccmux.ui.sidebar <session>", file=sys.stderr)
        print("       python -m ccmux.ui.sidebar --demo", file=sys.stderr)
        sys.exit(1)

    session = sys.argv[1]

    # PID tracking
    write_pid_file(session)
    atexit.register(remove_pid_file, session)

    app = SidebarApp(session=session)
    app.run()


if __name__ == "__main__":
    main()
