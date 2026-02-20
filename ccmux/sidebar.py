"""Textual TUI sidebar for ccmux - shows instances with click-to-switch navigation.

Launch: python -m ccmux.sidebar <session>
"""

import asyncio
import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from ccmux import state

# PID tracking directory
SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"

POLL_INTERVAL = 5.0


class InstanceRow(Static):
    """A clickable row representing a single instance."""

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

    def update_state(self, is_active: bool, is_current: bool, is_last: bool) -> None:
        """Update this row's display without remounting."""
        self.is_active = is_active
        self.is_current = is_current
        connector = "\u2514\u2500\u2500" if is_last else "\u251c\u2500\u2500"
        indicator = "\u25cf" if is_active else "\u25cb"
        self.update(f"{connector} {indicator} {self.instance_name:<10} {self.instance_type}")
        if is_current:
            self.add_class("current")
        else:
            self.remove_class("current")

    def on_click(self) -> None:
        """Switch to this instance's tmux window in the inner session."""
        try:
            subprocess.run(
                ["tmux", "select-window", "-t", f"{self.session}-inner:{self.instance_name}"],
                check=True,
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
        self._last_snapshot: list[tuple] = []

    def compose(self) -> ComposeResult:
        yield Static("CCMUX", id="title")
        yield Static(f"Session: {self._initial_session}", id="header")
        yield Static("", id="spacer")
        yield Vertical(id="instance-list")

    async def on_mount(self) -> None:
        self.session_name = await self._resolve_session_name()
        await self._refresh_instances()
        self.set_interval(POLL_INTERVAL, self._poll_refresh)
        self._register_signal_handler()

    async def _resolve_session_name(self) -> str:
        """Get the current tmux session name (survives renames)."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["tmux", "display-message", "-p", "#S"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return self._initial_session

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

    async def _get_tmux_window_ids(self) -> set[str]:
        """Get active window IDs from the inner tmux session."""
        inner = f"{self.session_name}-inner"
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["tmux", "list-windows", "-t", inner, "-F", "#{window_id}"],
                capture_output=True,
                text=True,
                check=True,
            )
            return set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()
        except subprocess.CalledProcessError:
            return set()

    def _build_demo_snapshot(self) -> list[tuple]:
        """Build dummy snapshot data for testing outside tmux."""
        return [
            ("my-project", "main", "main", True, True),
            ("my-project", "feat-auth", "worktree", True, False),
            ("my-project", "fix-bug", "worktree", False, False),
            ("other-repo", "default", "main", True, False),
            ("other-repo", "refactor", "worktree", False, False),
        ]

    async def _build_snapshot(self) -> list[tuple]:
        """Build a comparable snapshot of the current instance state."""
        if self._demo:
            return self._build_demo_snapshot()

        instances = state.get_all_worktrees(self.session_name)
        if not instances:
            return []

        active_window_ids = await self._get_tmux_window_ids()
        current_instance = await self._get_current_instance_name()

        snapshot = []
        for inst in instances:
            repo_name = Path(inst["repo_path"]).name
            is_active = inst.get("tmux_window_id") in active_window_ids
            is_current = inst["name"] == current_instance
            inst_type = "worktree" if inst.get("is_worktree", True) else "main"
            snapshot.append((repo_name, inst["name"], inst_type, is_active, is_current))
        return snapshot

    def _build_widgets(self, snapshot: list[tuple]) -> list[Static]:
        """Build widget list from a snapshot."""
        if not snapshot:
            return [Static("  No instances", classes="dim")]

        repos: dict[str, list[tuple]] = {}
        for entry in snapshot:
            repos.setdefault(entry[0], []).append(entry)

        widgets: list[Static] = []
        for repo_name, repo_entries in repos.items():
            widgets.append(RepoHeader(f"{repo_name}/", id=f"repo-{repo_name}"))
            for i, (_, inst_name, inst_type, is_active, is_current) in enumerate(repo_entries):
                widgets.append(
                    InstanceRow(
                        instance_name=inst_name,
                        instance_type=inst_type,
                        is_active=is_active,
                        is_current=is_current,
                        is_last=(i == len(repo_entries) - 1),
                        session=self.session_name,
                        id=f"inst-{inst_name}",
                    )
                )
        return widgets

    async def _refresh_instances(self) -> None:
        """Refresh the instance list, updating in place when possible."""
        self.session_name = await self._resolve_session_name()
        header = self.query_one("#header", Static)
        header.update(f"Session: {self.session_name}")

        snapshot = await self._build_snapshot()
        if snapshot == self._last_snapshot:
            return

        old_names = [entry[1] for entry in self._last_snapshot]
        new_names = [entry[1] for entry in snapshot]
        self._last_snapshot = snapshot

        if old_names == new_names and old_names:
            # Same structure — update existing rows in place
            repos: dict[str, list[tuple]] = {}
            for entry in snapshot:
                repos.setdefault(entry[0], []).append(entry)
            for repo_entries in repos.values():
                for i, (_, inst_name, inst_type, is_active, is_current) in enumerate(repo_entries):
                    row = self.query_one(f"#inst-{inst_name}", InstanceRow)
                    row.update_state(is_active, is_current, is_last=(i == len(repo_entries) - 1))
            return

        # Structure changed — full rebuild
        container = self.query_one("#instance-list", Vertical)
        await container.remove_children()
        await container.mount(*self._build_widgets(snapshot))
        self.refresh(layout=True)

    async def _poll_refresh(self) -> None:
        """Periodic refresh via polling."""
        await self._refresh_instances()

    def _register_signal_handler(self) -> None:
        """Register SIGUSR1 handler for instant refresh on state changes."""
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGUSR1, self._on_sigusr1)
        except (ValueError, OSError):
            pass

    def _reload_css_from_disk(self) -> None:
        """Re-read and apply CSS from disk."""
        css_paths = self.css_path
        if css_paths:
            stylesheet = self.stylesheet.copy()
            stylesheet.read_all(css_paths)
            stylesheet.parse()
            self.stylesheet = stylesheet
            self.stylesheet.update(self)
            for screen in self.screen_stack:
                self.stylesheet.update(screen)

    def _on_sigusr1(self) -> None:
        """Handle SIGUSR1 signal by scheduling a refresh."""
        self._reload_css_from_disk()
        self.run_worker(self._refresh_instances())


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
