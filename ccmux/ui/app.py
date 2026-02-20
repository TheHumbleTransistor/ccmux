"""Textual TUI sidebar for ccmux - shows instances with click-to-switch navigation.

Launch: python -m ccmux.sidebar <session>
"""

import asyncio
import atexit
import logging
import signal
import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ccmux import state
from ccmux.ui.demo import build_demo_snapshot
from ccmux.ui.pid import write_pid_file, remove_pid_file
from ccmux.ui.widgets import NonInteractiveStatic, InstanceRow, RepoHeader

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


def _group_by_repo(snapshot: list[tuple]) -> dict[str, list[tuple]]:
    """Group snapshot entries by repo name (first element of each tuple)."""
    repos: dict[str, list[tuple]] = {}
    for entry in snapshot:
        repos.setdefault(entry[0], []).append(entry)
    return repos


def _resolve_alert_state(flags: dict[str, bool] | None) -> str | None:
    """Determine alert state from window flags (bell > silence-reset > activity)."""
    if not flags:
        return None
    if flags.get("bell"):
        return "bell"
    if flags.get("silence"):
        return None  # silence overrides activity
    if flags.get("activity"):
        return "activity"
    return None


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

    async def _get_current_window_id(self) -> str | None:
        """Query the inner tmux session for the currently active window ID."""
        inner = f"{self.session_name}-inner"
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["tmux", "display-message", "-t", inner, "-p", "#{window_id}"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip() or None
        except subprocess.CalledProcessError:
            return None

    async def _get_current_instance_name(self) -> str | None:
        """Resolve the current instance name by dynamically finding our window."""
        window_id = await self._get_current_window_id()
        if not window_id:
            return None
        session_data = state.get_session(self.session_name)
        if not session_data:
            return None
        instances = session_data.get("instances", session_data.get("worktrees", {}))
        for inst_name, inst_data in instances.items():
            if inst_data.get("tmux_window_id") == window_id:
                return inst_name
        return None

    async def _get_tmux_window_flags(self) -> dict[str, dict[str, bool]]:
        """Get window IDs and their bell/activity/silence flags from inner session."""
        inner = f"{self.session_name}-inner"
        fmt = "#{window_id}|#{@ccmux_bell}|#{window_activity_flag}|#{window_silence_flag}"
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["tmux", "list-windows", "-t", inner, "-F", fmt],
                capture_output=True,
                text=True,
                check=True,
            )
            flags: dict[str, dict[str, bool]] = {}
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    wid = parts[0]
                    flags[wid] = {
                        "bell": parts[1] == "1",
                        "activity": parts[2] == "1",
                        "silence": parts[3] == "1",
                    }
            return flags
        except subprocess.CalledProcessError:
            return {}

    async def _build_snapshot(self) -> list[tuple]:
        """Build a comparable snapshot of the current instance state."""
        if self._demo:
            snapshot = build_demo_snapshot(self._demo_tick)
            self._demo_tick += 1
            return snapshot

        instances = state.get_all_worktrees(self.session_name)
        if not instances:
            return []

        window_flags = await self._get_tmux_window_flags()
        current_instance = await self._get_current_instance_name()

        snapshot = []
        for inst in instances:
            repo_name = Path(inst["repo_path"]).name
            wid = inst.get("tmux_window_id")
            is_active = wid in window_flags
            is_current = inst["name"] == current_instance
            inst_type = "worktree" if inst.get("is_worktree", True) else "main"
            alert_state = _resolve_alert_state(window_flags.get(wid))
            snapshot.append((repo_name, inst["name"], inst_type, is_active, is_current, alert_state))
        return snapshot

    def _build_widgets(self, snapshot: list[tuple]) -> list[Static]:
        """Build widget list from a snapshot."""
        if not snapshot:
            return [NonInteractiveStatic("  No instances", classes="dim")]

        repos = _group_by_repo(snapshot)

        widgets: list[Static] = []
        repo_items = list(repos.items())
        for idx, (repo_name, repo_entries) in enumerate(repo_items):
            if idx > 0:
                widgets.append(NonInteractiveStatic("", classes="repo-spacer"))
            widgets.append(RepoHeader(f"\u25cf {repo_name}/", id=f"repo-{repo_name}"))
            for i, (_, inst_name, inst_type, is_active, is_current, alert_state) in enumerate(
                repo_entries
            ):
                widgets.append(
                    InstanceRow(
                        instance_name=inst_name,
                        instance_type=inst_type,
                        is_active=is_active,
                        is_current=is_current,
                        is_last=(i == len(repo_entries) - 1),
                        session=self.session_name,
                        alert_state=alert_state,
                        id=f"inst-{inst_name}",
                    )
                )
        return widgets

    async def _refresh_instances(self, caller: str = "unknown") -> None:
        """Refresh the instance list with a full rebuild every time."""
        async with self._refresh_lock:
            log.debug("refresh START caller=%s", caller)

            snapshot = await self._build_snapshot()
            # if snapshot == self._last_snapshot:
            #     log.debug("refresh SHORT-CIRCUIT (no change)")
            #     return

            # self._last_snapshot = snapshot

            log.debug("refresh REBUILD caller=%s", caller)
            container = self.query_one("#instance-list", Vertical)
            new_widgets = self._build_widgets(snapshot)
            await container.remove_children()
            await container.mount(*new_widgets)

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        await self._refresh_instances(caller="poll")

    def _register_signal_handler(self) -> None:
    #     """Register SIGUSR1 handler for instant refresh on state changes."""
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
    """Entry point: python -m ccmux.sidebar <session>"""
    if "--demo" in sys.argv:
        app = SidebarApp(session="demo", demo=True)
        app.run()
        return

    if len(sys.argv) < 2:
        print("Usage: python -m ccmux.sidebar <session>", file=sys.stderr)
        print("       python -m ccmux.sidebar --demo", file=sys.stderr)
        sys.exit(1)

    session = sys.argv[1]

    # PID tracking
    write_pid_file(session)
    atexit.register(remove_pid_file, session)

    app = SidebarApp(session=session)
    app.run()


if __name__ == "__main__":
    main()
