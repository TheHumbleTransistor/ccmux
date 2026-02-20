"""Textual TUI sidebar for ccmux - shows instances with click-to-switch navigation.

Launch: python -m ccmux.sidebar <session>
"""

import asyncio
import atexit
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from ccmux import state

# PID tracking directory
SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"

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


class InstanceRow(Static):
    """A clickable 3-row block: tree pad above, content, tree pad below."""

    def __init__(
        self,
        instance_name: str,
        instance_type: str,
        is_active: bool,
        is_current: bool,
        is_last: bool,
        session: str,
        alert_state: str | None = None,
        **kwargs,
    ) -> None:
        self.instance_name = instance_name
        self.instance_type = instance_type
        self.is_active = is_active
        self.is_current = is_current
        self.is_last = is_last
        self.session = session
        self.alert_state = alert_state
        super().__init__(self._render_label(), **kwargs)
        if is_current:
            self.add_class("current")
        self._apply_alert_class(alert_state)

    def _render_label(self) -> str:
        connector = "\u2514\u2500\u2500" if self.is_last else "\u251c\u2500\u2500"
        indicator = "\u25cf" if self.is_active else "\u25cb"
        content = f"{connector} {indicator} {self.instance_name:<10} {self.instance_type}"
        bottom = "" if self.is_last else "\u2502"
        return f"\u2502\n{content}\n{bottom}"

    def _apply_alert_class(self, alert_state: str | None) -> None:
        """Add/remove bell and activity CSS classes based on alert state."""
        if alert_state == "bell":
            self.add_class("bell")
            self.remove_class("activity")
        elif alert_state == "activity":
            self.add_class("activity")
            self.remove_class("bell")
        else:
            self.remove_class("bell")
            self.remove_class("activity")

    def update_state(
        self, is_active: bool, is_current: bool, is_last: bool, alert_state: str | None = None
    ) -> None:
        """Update this row's display without remounting."""
        self.is_active = is_active
        self.is_current = is_current
        self.is_last = is_last
        self.alert_state = alert_state
        self.update(self._render_label())
        if is_current:
            self.add_class("current")
        else:
            self.remove_class("current")
        self._apply_alert_class(alert_state)

    def on_click(self) -> None:
        """Switch to this instance's tmux window in the inner and bash sessions."""
        try:
            subprocess.run(
                ["tmux", "select-window", "-t", f"{self.session}-inner:{self.instance_name}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass
        try:
            subprocess.run(
                ["tmux", "select-window", "-t", f"{self.session}-bash:{self.instance_name}"],
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass


class RepoHeader(Static):
    """Non-clickable section header for a repository group."""


class SidebarApp(App):
    """Textual sidebar showing ccmux instances for click-to-switch navigation."""

    CSS_PATH = "sidebar.tcss"

    session_name: reactive[str] = reactive("")

    def __init__(self, session: str, demo: bool = False) -> None:
        super().__init__()
        self._initial_session = session
        self._demo = demo
        self._demo_tick = 0
        self._last_snapshot: list[tuple] = []
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield Static("CCMUX", id="title")
        yield Static(f"Session: {self._initial_session}", id="header")
        yield Static("", id="spacer")
        yield Vertical(id="instance-list")

    async def on_mount(self) -> None:
        self.session_name = self._initial_session
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

    def _build_demo_snapshot(self) -> list[tuple]:
        """Build varying snapshot data to exercise refresh/rebuild paths."""
        tick = self._demo_tick
        self._demo_tick += 1

        # Cycle current instance among three instances
        current_idx = tick % 3
        # Cycle alert states: None → bell → activity → None
        alert_cycle = [None, "bell", "activity", None]
        alert_for = lambda offset: alert_cycle[(tick + offset) % len(alert_cycle)]

        base = [
            ("my-project", "main", "main", True, current_idx == 0, alert_for(0)),
            ("my-project", "feat-auth", "worktree", True, current_idx == 1, alert_for(1)),
            ("my-project", "fix-bug", "worktree", False, current_idx == 2, alert_for(2)),
            ("other-repo", "default", "main", True, False, alert_for(3)),
            ("other-repo", "refactor", "worktree", False, False, None),
        ]

        # Every 8th tick, add an extra instance (tests full rebuild path)
        if (tick // 4) % 2 == 1:
            base.append(("other-repo", "hotfix", "worktree", True, False, "bell"))

        return base

    @staticmethod
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

    async def _build_snapshot(self) -> list[tuple]:
        """Build a comparable snapshot of the current instance state."""
        if self._demo:
            return self._build_demo_snapshot()

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
            alert_state = self._resolve_alert_state(window_flags.get(wid))
            snapshot.append((repo_name, inst["name"], inst_type, is_active, is_current, alert_state))
        return snapshot

    def _build_widgets(self, snapshot: list[tuple]) -> list[Static]:
        """Build widget list from a snapshot."""
        if not snapshot:
            return [Static("  No instances", classes="dim")]

        repos: dict[str, list[tuple]] = {}
        for entry in snapshot:
            repos.setdefault(entry[0], []).append(entry)

        widgets: list[Static] = []
        repo_items = list(repos.items())
        for idx, (repo_name, repo_entries) in enumerate(repo_items):
            if idx > 0:
                widgets.append(Static("", classes="repo-spacer"))
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
        """Refresh the instance list, updating in place when possible."""
        async with self._refresh_lock:
            t0 = time.monotonic()
            log.debug("refresh START caller=%s", caller)

            snapshot = await self._build_snapshot()
            if snapshot == self._last_snapshot:
                log.debug("refresh SHORT-CIRCUIT (no change) %.1fms", (time.monotonic() - t0) * 1000)
                return

            old_names = [entry[1] for entry in self._last_snapshot]
            new_names = [entry[1] for entry in snapshot]
            self._last_snapshot = snapshot

            if old_names == new_names and old_names:
                log.debug("refresh SAME-STRUCTURE update")
                t1 = time.monotonic()
                with self.batch_update():
                    repos: dict[str, list[tuple]] = {}
                    for entry in snapshot:
                        repos.setdefault(entry[0], []).append(entry)
                    for repo_entries in repos.values():
                        for i, (_, inst_name, inst_type, is_active, is_current, alert_state) in enumerate(
                            repo_entries
                        ):
                            row = self.query_one(f"#inst-{inst_name}", InstanceRow)
                            row.update_state(
                                is_active, is_current, is_last=(i == len(repo_entries) - 1),
                                alert_state=alert_state,
                            )
                log.debug("refresh SAME-STRUCTURE done batch=%.1fms total=%.1fms",
                          (time.monotonic() - t1) * 1000, (time.monotonic() - t0) * 1000)
                return

            # Structure changed — full rebuild
            log.debug("refresh FULL-REBUILD old=%s new=%s", old_names, new_names)
            container = self.query_one("#instance-list", Vertical)
            new_widgets = self._build_widgets(snapshot)
            t1 = time.monotonic()
            with self.batch_update():
                await container.remove_children()
                await container.mount(*new_widgets)
            log.debug("refresh FULL-REBUILD done mount=%.1fms total=%.1fms",
                      (time.monotonic() - t1) * 1000, (time.monotonic() - t0) * 1000)

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        log.debug("poll_refresh triggered")
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
            self._refresh_instances(caller="signal"), exclusive=True, group="refresh",
        )


# --- PID file management ---

def _pid_dir(session: str) -> Path:
    return SIDEBAR_PIDS_DIR / session


def write_pid_file(session: str) -> Path:
    """Write current PID to tracking directory. Returns the pid file path."""
    pid_dir = _pid_dir(session)
    pid_dir.mkdir(parents=True, exist_ok=True)
    pid_file = pid_dir / f"{os.getpid()}.pid"
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid_file(session: str) -> None:
    """Remove current PID file on exit."""
    pid_file = _pid_dir(session) / f"{os.getpid()}.pid"
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


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
