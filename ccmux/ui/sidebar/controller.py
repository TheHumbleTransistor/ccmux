"""Sidebar application controller — Textual app, polling, signals."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical

from ccmux.ui.sidebar import model, view
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

    def __init__(
        self,
        session: str,
        snapshot_fn: Callable[[], Awaitable[list[tuple]]] | None = None,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        super().__init__()
        self.session_name = session
        self._snapshot_fn = snapshot_fn
        self._poll_interval = poll_interval
        self._last_snapshot: list[tuple] = []
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield NonInteractiveStatic("CCMUX", id="title")
        yield NonInteractiveStatic(f"Session: {self.session_name}", id="header")
        yield NonInteractiveStatic("", id="spacer")
        yield Vertical(id="instance-list")

    async def on_mount(self) -> None:
        await self._refresh_instances(caller="mount")
        self.set_interval(self._poll_interval, self._poll_refresh)
        self._register_signal_handler()

    async def _refresh_instances(self, caller: str = "unknown") -> None:
        """Refresh the instance list with a full rebuild every time."""
        async with self._refresh_lock:
            log.debug("refresh START caller=%s", caller)

            if self._snapshot_fn is not None:
                snapshot = await self._snapshot_fn()
            else:
                snapshot = await model.build_snapshot(self.session_name)

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
