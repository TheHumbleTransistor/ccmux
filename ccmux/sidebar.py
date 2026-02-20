"""Textual TUI sidebar for ccmux - shows instances with click-to-switch navigation.

Launch: python -m ccmux.sidebar <session> <window_id>
"""

import asyncio
import atexit
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from ccmux import state

# PID tracking directory
SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"

POLL_INTERVAL = 5.0


class InstanceRow(Static):
    """A clickable row representing a single instance."""

    DEFAULT_CSS = """
    InstanceRow {
        height: 1;
        padding: 0 1;
        color: #9e9e9e;
    }
    InstanceRow:hover {
        background: #3a3a3a;
    }
    InstanceRow.current {
        background: #3a3a3a;
        color: #bcbcbc;
        text-style: bold;
    }
    """

    def __init__(
        self,
        instance_name: str,
        instance_type: str,
        is_active: bool,
        is_current: bool,
        is_last: bool,
        session: str,
        **kwargs,
    ) -> None:
        self.instance_name = instance_name
        self.instance_type = instance_type
        self.is_active = is_active
        self.is_current = is_current
        self.session = session
        connector = "\u2514\u2500\u2500" if is_last else "\u251c\u2500\u2500"
        indicator = "\u25cf" if is_active else "\u25cb"
        label = f"{connector} {indicator} {instance_name:<10} {instance_type}"
        super().__init__(label, **kwargs)
        if is_current:
            self.add_class("current")

    def on_click(self) -> None:
        """Switch to this instance's tmux window."""
        try:
            subprocess.run(
                ["tmux", "select-window", "-t", f"{self.session}:{self.instance_name}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass


class RepoHeader(Static):
    """Non-clickable section header for a repository group."""

    DEFAULT_CSS = """
    RepoHeader {
        height: 1;
        padding: 0 1;
        color: #d7af5f;
        text-style: bold;
    }
    """


class SidebarApp(App):
    """Textual sidebar showing ccmux instances for click-to-switch navigation."""

    CSS = """
    Screen {
        background: #262626;
        layout: vertical;
    }
    #title {
        height: 1;
        padding: 0 1;
        color: #d7af5f;
        background: #262626;
        text-style: bold;
    }
    #header {
        height: 1;
        padding: 0 1;
        background: #262626;
        color: #bcbcbc;
    }
    #spacer {
        height: 1;
        background: #262626;
    }
    #instance-list {
        background: #262626;
    }
    #instance-list:focus {
        border: none;
    }
    """

    session_name: reactive[str] = reactive("")

    def __init__(self, session: str, window_id: str) -> None:
        super().__init__()
        self._initial_session = session
        self._window_id = window_id
        self._last_snapshot: list[tuple] = []

    def compose(self) -> ComposeResult:
        yield Static("CCMUX", id="title")
        yield Static(f"Session: {self._initial_session}", id="header")
        yield Static("", id="spacer")
        yield VerticalScroll(id="instance-list")

    def on_mount(self) -> None:
        self.session_name = self._resolve_session_name()
        self._refresh_instances()
        self.set_interval(POLL_INTERVAL, self._poll_refresh)
        self._register_signal_handler()

    def _resolve_session_name(self) -> str:
        """Get the current tmux session name (survives renames)."""
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#S"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return self._initial_session

    def _get_current_instance_name(self) -> str | None:
        """Resolve the current instance name from our window_id."""
        session_data = state.get_session(self.session_name)
        if not session_data:
            return None
        instances = session_data.get("instances", session_data.get("worktrees", {}))
        for inst_name, inst_data in instances.items():
            if inst_data.get("tmux_window_id") == self._window_id:
                return inst_name
        return None

    def _get_tmux_window_ids(self) -> set[str]:
        """Get active window IDs from tmux for this session."""
        try:
            result = subprocess.run(
                ["tmux", "list-windows", "-t", self.session_name, "-F", "#{window_id}"],
                capture_output=True,
                text=True,
                check=True,
            )
            return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
        except subprocess.CalledProcessError:
            return set()

    def _build_snapshot(self) -> list[tuple]:
        """Build a comparable snapshot of the current instance state."""
        instances = state.get_all_worktrees(self.session_name)
        if not instances:
            return []

        active_window_ids = self._get_tmux_window_ids()
        current_instance = self._get_current_instance_name()

        snapshot = []
        for inst in instances:
            repo_name = Path(inst["repo_path"]).name
            is_active = inst.get("tmux_window_id") in active_window_ids
            is_current = inst["name"] == current_instance
            inst_type = "worktree" if inst.get("is_worktree", True) else "main"
            snapshot.append((repo_name, inst["name"], inst_type, is_active, is_current))
        return snapshot

    def _refresh_instances(self) -> None:
        """Rebuild the instance list from state + tmux, only if data changed."""
        self.session_name = self._resolve_session_name()
        header = self.query_one("#header", Static)
        header.update(f"Session: {self.session_name}")

        snapshot = self._build_snapshot()
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot

        container = self.query_one("#instance-list", VerticalScroll)
        container.remove_children()

        if not snapshot:
            container.mount(Static("  No instances", classes="dim"))
            return

        # Group by repo
        repos: dict[str, list[tuple]] = {}
        for entry in snapshot:
            repo_name = entry[0]
            repos.setdefault(repo_name, []).append(entry)

        for repo_name, repo_entries in repos.items():
            container.mount(RepoHeader(f"{repo_name}/"))
            for i, (_, inst_name, inst_type, is_active, is_current) in enumerate(repo_entries):
                container.mount(
                    InstanceRow(
                        instance_name=inst_name,
                        instance_type=inst_type,
                        is_active=is_active,
                        is_current=is_current,
                        is_last=(i == len(repo_entries) - 1),
                        session=self.session_name,
                    )
                )

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        self._refresh_instances()

    def _register_signal_handler(self) -> None:
        """Register SIGUSR1 handler for instant refresh on state changes."""
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGUSR1, self._on_sigusr1)
        except (ValueError, OSError):
            pass

    def _on_sigusr1(self) -> None:
        """Handle SIGUSR1 signal by scheduling a refresh."""
        self.call_from_thread(self._refresh_instances)


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
    """Entry point: python -m ccmux.sidebar <session> <window_id>"""
    if len(sys.argv) < 3:
        print("Usage: python -m ccmux.sidebar <session> <window_id>", file=sys.stderr)
        sys.exit(1)

    session = sys.argv[1]
    window_id = sys.argv[2]

    # PID tracking
    write_pid_file(session)
    atexit.register(remove_pid_file, session)

    app = SidebarApp(session=session, window_id=window_id)
    app.run()


if __name__ == "__main__":
    main()
