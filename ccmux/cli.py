#!/usr/bin/env python3
"""Claude Code Multiplexer CLI - Manage multiple Claude Code instances."""

import inspect
import os
import random
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from cyclopts import Parameter
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ccmux import state
from ccmux.config import run_post_create
from ccmux.tmux_config import apply_tmux_config

# Default session name
DEFAULT_SESSION = "default"


# Common parameters shared across all commands
@dataclass
class Common:
    """Common parameters for all commands."""
    session: str = DEFAULT_SESSION


# Type alias for Common config parameter
CommonConfig = Annotated[Common, Parameter(parse=False, show=False)]


console = Console()
app = cyclopts.App(
    name="ccmux",
    help="Claude Code Multiplexer - Manage multiple Claude Code instances.",
)

session_app = cyclopts.App(name="session", help="Manage ccmux sessions")
app.command(session_app)

sidebar_app = cyclopts.App(name="sidebar", help="Manage sidebar panes")
app.command(sidebar_app)

# Top-level aliases: rewrite these to sub-app paths in meta
TOP_LEVEL_ALIASES = {
    "attach": ("session", "attach"),
}


# --- Utility Functions ---

ANIMALS = [
    "otter", "lynx", "fox", "wolf", "bear", "wren", "robin", "hawk", "eagle", "falcon",
    "heron", "swan", "crane", "goose", "duck", "loon", "ibis", "kiwi", "dingo", "quokka",
    "bison", "yak", "ibex", "oryx", "okapi", "tapir", "panda", "koala", "wombat",
    "gecko", "skink", "python", "mamba", "cobra", "viper", "boar", "mole", "vole",
    "puma", "jaguar", "leopard", "tiger", "lion", "cheetah", "serval", "caracal", "ocelot",
    "kudu", "eland", "gazelle", "impala", "springbok", "hyena", "dolphin", "orca",
    "beluga", "manatee", "seal", "walrus", "penguin", "salmon", "trout", "sturgeon",
    "carp", "pike", "marlin", "tuna", "halibut", "cod", "owl", "kestrel", "harrier",
    "kite", "buzzard", "condor", "vulture", "beetle", "moth", "ant", "wasp", "bee",
    "dragonfly", "mantis", "beaver", "muskrat", "hare", "rabbit", "pika",
]


def sanitize_name(name: str) -> str:
    """Sanitize a name for use as a branch/worktree name."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9-]+', '-', name)
    name = re.sub(r'^-+|-+$', '', name)
    name = re.sub(r'-{2,}', '-', name)
    return name


def generate_animal_name() -> str:
    """Generate a random animal name."""
    return random.choice(ANIMALS)


def get_repo_root() -> Optional[Path]:
    """Get the git repository root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_default_branch() -> Optional[str]:
    """Get the default branch name (main, master, etc.)."""
    try:
        result = subprocess.run(
            ["git", "remote", "show", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Look for line like: "HEAD branch: main"
        for line in result.stdout.split("\n"):
            if "HEAD branch:" in line:
                return line.split(":")[-1].strip()
    except subprocess.CalledProcessError:
        pass

    return None


def worktree_exists(worktree_path: Path) -> bool:
    """Check if a worktree exists and is registered."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        return str(worktree_path) in result.stdout
    except subprocess.CalledProcessError:
        return False


def branch_exists(branch_name: str) -> bool:
    """Check if a git branch exists."""
    try:
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def tmux_session_exists(session_name: str) -> bool:
    """Check if a tmux session exists."""
    try:
        subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def get_current_tmux_window() -> Optional[str]:
    """Get the current tmux window name if running inside tmux."""
    if "TMUX" not in os.environ:
        return None

    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#W"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_tmux_session() -> Optional[str]:
    """Get the current tmux session name if running inside tmux."""
    if "TMUX" not in os.environ:
        return None

    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_tmux_windows(session_name: str) -> list[str]:
    """Get all window names in a tmux session."""
    if not tmux_session_exists(session_name):
        return []

    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session_name, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []


def is_window_active_in_session(session_name: str, tmux_window_id: Optional[str]) -> bool:
    """Check if a tmux window ID exists in a specific session.

    Uses session-scoped window listing instead of global display-message
    to avoid false positives from recycled window IDs after server restarts.

    Args:
        session_name: The tmux session name to check within
        tmux_window_id: The @-prefixed window ID (e.g., "@0")

    Returns:
        True if the window exists in the specified session
    """
    if not tmux_window_id or not tmux_session_exists(session_name):
        return False

    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session_name, "-F", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
        window_ids = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return tmux_window_id in window_ids
    except subprocess.CalledProcessError:
        return False


def get_all_worktrees(repo_root: Path) -> list[dict[str, str]]:
    """Get all worktrees in the .worktrees directory.

    Returns a list of dicts with keys: name, path, branch
    """
    worktrees_dir = repo_root / ".worktrees"
    if not worktrees_dir.exists():
        return []

    worktrees = []
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse porcelain output
        current_worktree = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                if current_worktree:
                    worktrees.append(current_worktree)
                current_worktree = {"path": line[9:]}
            elif line.startswith("branch "):
                current_worktree["branch"] = line[7:].replace("refs/heads/", "")
            elif line.startswith("detached"):
                current_worktree["branch"] = "(detached)"

        if current_worktree:
            worktrees.append(current_worktree)

        # Filter to only .worktrees and add name
        filtered = []
        for wt in worktrees:
            path = Path(wt["path"])
            if path.parent == worktrees_dir:
                wt["name"] = path.name
                filtered.append(wt)

        return filtered
    except subprocess.CalledProcessError:
        return []


# --- Sidebar Helpers ---

SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"


def _add_sidebar_pane(session: str, window_id: str) -> None:
    """Add a sidebar pane to a tmux window via split.

    Creates a left-side pane (25% width) running the Textual sidebar app.
    Skips if terminal is too narrow (< 60 columns).
    """
    # Check window width - skip sidebar for very narrow terminals
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", window_id, "-p", "#{window_width}"],
            capture_output=True, text=True, check=True,
        )
        width = int(result.stdout.strip())
        if width < 60:
            return
    except (subprocess.CalledProcessError, ValueError):
        # If we can't check width, proceed anyway
        pass

    python_exe = sys.executable or "python3"
    sidebar_cmd = (
        f"COLORTERM=truecolor {python_exe} -m ccmux.sidebar {session} {window_id} ; "
        f"echo 'Sidebar exited. Press enter to close.' ; read"
    )

    try:
        subprocess.run(
            [
                "tmux", "split-window",
                "-t", window_id,
                "-bh",
                "-l", "25%",
                "-d",
                sidebar_cmd,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass


def _ensure_sidebar_pane(session: str, window_id: str) -> None:
    """Check if a window has a sidebar pane; add one if missing.

    Detects the sidebar by counting panes: a ccmux window should have 2
    (sidebar + main). If only 1 pane exists, the sidebar is missing.
    """
    if not window_id:
        return

    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", window_id, "-F", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        )
        pane_count = len(result.stdout.strip().split("\n"))
    except subprocess.CalledProcessError:
        return

    if pane_count < 2:
        _add_sidebar_pane(session, window_id)


def _ensure_all_sidebars(session: str) -> None:
    """Ensure every active window in a session has a sidebar pane."""
    instances = state.get_all_worktrees(session)
    for inst in instances:
        tmux_window_id = inst.get("tmux_window_id")
        if tmux_window_id and is_window_active_in_session(session, tmux_window_id):
            _ensure_sidebar_pane(session, tmux_window_id)


def _notify_sidebars(session: str) -> None:
    """Send SIGUSR1 to all active sidebar processes for a session.

    Reads PID files from ~/.ccmux/sidebar_pids/<session>/ and signals each.
    Removes stale PID files when the process no longer exists.
    """
    pid_dir = SIDEBAR_PIDS_DIR / session
    if not pid_dir.is_dir():
        return

    for pid_file in pid_dir.iterdir():
        if not pid_file.suffix == ".pid":
            continue
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGUSR1)
        except (ProcessLookupError, ValueError):
            # Process gone or invalid PID - clean up stale file
            try:
                pid_file.unlink(missing_ok=True)
            except OSError:
                pass
        except PermissionError:
            pass


def _kill_sidebar_pane(window_id: str) -> bool:
    """Kill the sidebar pane in a tmux window.

    Identifies the sidebar pane by checking pane commands for 'ccmux.sidebar'.
    Returns True if a sidebar pane was found and killed.
    """
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", window_id, "-F", "#{pane_id} #{pane_start_command}"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return False

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        if "ccmux.sidebar" in line:
            pane_id = line.split()[0]
            try:
                subprocess.run(
                    ["tmux", "kill-pane", "-t", pane_id],
                    check=True, capture_output=True,
                )
                return True
            except subprocess.CalledProcessError:
                pass
    return False


def _reload_sidebar_pane(session: str, window_id: str) -> None:
    """Kill and re-add the sidebar pane for a tmux window."""
    _kill_sidebar_pane(window_id)
    _add_sidebar_pane(session, window_id)


# --- Detection Helpers ---

def detect_current_ccmux_session() -> Optional[tuple[str, dict]]:
    """Detect the current ccmux session from tmux environment.

    Returns (session_name, session_data) or None.
    """
    tmux_session = get_current_tmux_session()
    if not tmux_session:
        return None

    session_data = state.get_session(tmux_session)
    if session_data:
        return (tmux_session, session_data)
    return None


def detect_current_ccmux_instance() -> Optional[tuple[str, str, dict]]:
    """Detect the current ccmux instance from tmux environment.

    Returns (session_name, instance_name, instance_data) or None.
    """
    if "TMUX" not in os.environ:
        return None

    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        tmux_window_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None

    return state.find_worktree_by_tmux_ids(tmux_session_id, tmux_window_id)


# --- Internal Helpers ---

def _display_session_table(session: str) -> None:
    """Display a table for a single session.

    Args:
        session: Session name to display
    """
    instances = state.get_all_worktrees(session)

    if not instances:
        console.print(f"\n[yellow]No instances found in session '{session}'.[/yellow]")
        return

    # Create Rich table
    table = Table(title=f"Claude Code Instances (session: {session})", show_header=True)
    table.add_column("Repository", style="yellow")
    table.add_column("Instance", style="cyan", no_wrap=True)
    table.add_column("Type", style="green")
    table.add_column("Branch")
    table.add_column("Status", style="bold")
    table.add_column("Tmux Window", style="blue")
    table.add_column("Path", style="dim")

    active_count = 0
    for inst in instances:
        name = inst["name"]
        repo_path = Path(inst["repo_path"])
        instance_path = Path(inst["instance_path"])
        tmux_window_id = inst.get("tmux_window_id")
        is_worktree = inst.get("is_worktree", True)  # Default to True for backward compat

        # Get repository name
        repo_name = repo_path.name

        # Get instance type
        instance_type = "worktree" if is_worktree else "root"

        # Get branch name from instance
        branch = "(unknown)"
        try:
            result = subprocess.run(
                ["git", "-C", str(instance_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            branch = result.stdout.strip()
            if branch == "HEAD":
                branch = "[dim](detached)[/dim]"
            else:
                branch = f"[magenta]{branch}[/magenta]"
        except subprocess.CalledProcessError:
            pass

        # Get tmux window name and check if active (session-scoped)
        tmux_window_name = ""
        status = "[dim]\u25cb Inactive[/dim]"
        if is_window_active_in_session(session, tmux_window_id):
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                tmux_window_name = result.stdout.strip()
            except subprocess.CalledProcessError:
                pass
            status = "[green]\u25cf Active[/green]"
            active_count += 1

        table.add_row(repo_name, name, instance_type, branch, status, tmux_window_name, str(instance_path))

    console.print()
    console.print(table)
    console.print()

    # Show summary
    total_count = len(instances)
    console.print(f"Total: {total_count} instances, {active_count} active, {total_count - active_count} inactive")
    console.print()


def _show_instance_info(session_name: str, instance_name: str, instance_data: dict) -> None:
    """Display info about a specific instance."""
    repo_path = Path(instance_data["repo_path"])
    repo_name = repo_path.name
    worktree_path = Path(instance_data["instance_path"])
    is_worktree = instance_data.get("is_worktree", True)

    try:
        branch_result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        branch = branch_result.stdout.strip()
        if branch == "HEAD":
            branch = "(detached)"
    except subprocess.CalledProcessError:
        branch = "unknown"

    console.print(f"\n[bold cyan]Instance:[/bold cyan]   {instance_name}")
    console.print(f"[bold cyan]Session:[/bold cyan]    {session_name}")
    console.print(f"[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[bold cyan]Type:[/bold cyan]       {'worktree' if is_worktree else 'main repo'}")
    console.print(f"[bold cyan]Branch:[/bold cyan]     {branch}")
    console.print(f"[bold cyan]Path:[/bold cyan]       {worktree_path}\n")


def _activate_all_in_session(session: str, no_confirm: bool = False) -> None:
    """Activate all inactive instances in a session."""
    worktrees = state.get_all_worktrees(session)

    if not worktrees:
        console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(0)

    # Check which are inactive (session-scoped)
    inactive_worktrees = []
    for wt in worktrees:
        if not is_window_active_in_session(session, wt.get("tmux_window_id")):
            inactive_worktrees.append(wt)

    if not inactive_worktrees:
        _ensure_all_sidebars(session)
        console.print("\n[yellow]No inactive instances to activate.[/yellow]")
        return

    console.print(f"\n[bold cyan]Found {len(inactive_worktrees)} inactive instance(s):[/bold cyan]")
    for wt in inactive_worktrees:
        console.print(f"  \u2022 {wt['name']}")
    console.print()

    if not no_confirm:
        if not Confirm.ask(f"Activate all {len(inactive_worktrees)} instance(s)?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    tmux_session_exists_flag = tmux_session_exists(session)

    activated_count = 0
    for i, wt in enumerate(inactive_worktrees):
        wt_name = wt["name"]
        wt_path = wt["instance_path"]

        launch_cmd = (
            f"echo 'Activating Claude Code in {wt_path}'; "
            f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
        )

        try:
            new_tmux_window_id = None

            if not tmux_session_exists_flag and i == 0:
                result = subprocess.run(
                    [
                        "tmux", "new-session",
                        "-d",
                        "-s", session,
                        "-n", wt_name,
                        "-c", wt_path,
                        "-P", "-F", "#{window_id}",
                        launch_cmd,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                new_tmux_window_id = result.stdout.strip()
                tmux_session_exists_flag = True
                console.print(f"  [green]\u2713[/green] Created tmux session and activated '{wt_name}'")

                if apply_tmux_config(session):
                    console.print(f"    [green]\u2713[/green] Applied ccmux tmux configuration")
                else:
                    console.print(f"    [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
                _add_sidebar_pane(session, new_tmux_window_id)
            else:
                result = subprocess.run(
                    [
                        "tmux", "new-window",
                        "-t", session,
                        "-n", wt_name,
                        "-c", wt_path,
                        "-P", "-F", "#{window_id}",
                        launch_cmd,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                new_tmux_window_id = result.stdout.strip()
                _add_sidebar_pane(session, new_tmux_window_id)
                console.print(f"  [green]\u2713[/green] Activated '{wt_name}'")

            # Update tmux IDs in state
            try:
                new_tmux_session_id = subprocess.run(
                    ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()
                state.update_tmux_ids(session, wt_name, new_tmux_session_id, new_tmux_window_id)
            except subprocess.CalledProcessError:
                pass

            activated_count += 1
        except subprocess.CalledProcessError as e:
            console.print(f"  [red]Error activating '{wt_name}':[/red] {e}")

    _ensure_all_sidebars(session)
    _notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Activated {activated_count} instance(s).")


def _activate_single_instance(session: str, name: str, no_confirm: bool = False) -> None:
    """Activate a single instance by name."""
    worktrees = state.get_all_worktrees(session)

    if not worktrees:
        console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(0)

    # Find the instance
    worktree = None
    for wt in worktrees:
        if wt["name"] == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found in session '{session}'.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list --session {session}[/cyan]")
        sys.exit(1)

    # Check if already active - ensure sidebar even if window exists
    if is_window_active_in_session(session, worktree.get("tmux_window_id")):
        _ensure_sidebar_pane(session, worktree["tmux_window_id"])
        console.print(f"[yellow]Instance '{name}' already has an active tmux window.[/yellow]")
        return

    wt_path = worktree["instance_path"]

    console.print(f"\n[bold cyan]Activating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Instance: {wt_path}")

    tmux_session_exists_flag = tmux_session_exists(session)

    launch_cmd = (
        f"echo 'Activating Claude Code in {wt_path}'; "
        f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
    )

    try:
        tmux_window_id = None

        if not tmux_session_exists_flag:
            result = subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", session,
                    "-n", name,
                    "-c", wt_path,
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            console.print(f"  [green]\u2713[/green] Created tmux session and activated '{name}'")

            if apply_tmux_config(session):
                console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
            _add_sidebar_pane(session, tmux_window_id)
        else:
            result = subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", session,
                    "-n", name,
                    "-c", wt_path,
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _add_sidebar_pane(session, tmux_window_id)

            subprocess.run(
                ["tmux", "select-window", "-t", f"{session}:{name}"],
                check=True,
            )
            console.print(f"  [green]\u2713[/green] Activated '{name}'")

        # Update tmux IDs in state
        try:
            tmux_session_id = subprocess.run(
                ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            state.update_tmux_ids(session, name, tmux_session_id, tmux_window_id)
        except subprocess.CalledProcessError:
            pass

        _ensure_all_sidebars(session)
        _notify_sidebars(session)
        console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
        console.print(f"Attach with: [cyan]ccmux attach --session {session}[/cyan]")

        # Auto-attach if not already in tmux
        if "TMUX" not in os.environ:
            console.print()
            if no_confirm or Confirm.ask("Attach to tmux session now?", default=True):
                os.execvp("tmux", ["tmux", "attach", "-t", session])

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error activating Claude Code:[/red] {e}", style="bold")
        sys.exit(1)


def _resolve_session_name(
    name: Optional[str],
    current: bool,
    common: Common,
    allow_interactive: bool = True,
) -> str:
    """Resolve a session name from positional arg, -c flag, or interactive selection.

    Args:
        name: Positional session name argument
        current: Whether -c/--current was passed
        common: Common config (for default session)
        allow_interactive: Whether to prompt if no name or -c given

    Returns:
        The resolved session name
    """
    if current:
        detected = detect_current_ccmux_session()
        if not detected:
            console.print("[red]Error:[/red] Not in a ccmux session.", style="bold")
            console.print("Run this from within a tmux window managed by ccmux, or provide a session name.")
            sys.exit(1)
        return detected[0]

    if name:
        return name

    if allow_interactive:
        all_state = state.load_state()
        sessions = list(all_state.get("sessions", {}).keys())
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            sys.exit(1)
        if len(sessions) == 1:
            return sessions[0]

        console.print("\n[bold]Sessions:[/bold]")
        for i, s in enumerate(sessions):
            console.print(f"  {i + 1}. {s}")

        choice = Prompt.ask(
            "\nSelect session",
            choices=[str(i + 1) for i in range(len(sessions))],
        )
        return sessions[int(choice) - 1]

    return common.session


# --- Session Sub-App Commands ---

@session_app.default
def session_info(name: Optional[str] = None, *, common: CommonConfig) -> None:
    """Show session info.

    Args:
        name: Session name to show info for (defaults to the --session value)
        common: Common parameters (session, etc.)
    """
    session_name = name if name else common.session
    session_data = state.get_session(session_name)

    if not session_data:
        console.print(f"[yellow]Session '{session_name}' not found.[/yellow]")
        console.print(f"\nCreate one with: [cyan]ccmux new --session {session_name}[/cyan]")
        return

    instances = session_data.get("instances", session_data.get("worktrees", {}))
    total = len(instances)

    active = 0
    for inst_data in instances.values():
        if is_window_active_in_session(session_name, inst_data.get("tmux_window_id")):
            active += 1

    tmux_status = "Running" if tmux_session_exists(session_name) else "Not running"

    console.print(f"\n[bold cyan]Session:[/bold cyan]    {session_name}")
    console.print(f"[bold cyan]Instances:[/bold cyan]  {total} ({active} active, {total - active} inactive)")
    console.print(f"[bold cyan]Tmux:[/bold cyan]       {tmux_status}\n")


@session_app.command(name="list")
def session_list(*, common: CommonConfig) -> None:
    """List all ccmux sessions with summary info."""
    all_state = state.load_state()
    sessions = all_state.get("sessions", {})

    if not sessions:
        console.print("\n[yellow]No sessions found.[/yellow]")
        console.print("Create one with: [cyan]ccmux new[/cyan]")
        return

    table = Table(title="ccmux Sessions", show_header=True)
    table.add_column("Session", style="cyan")
    table.add_column("Instances", justify="right")
    table.add_column("Active", justify="right", style="green")
    table.add_column("Tmux Status", style="bold")

    for session_name, session_data in sessions.items():
        instances = session_data.get("instances", session_data.get("worktrees", {}))
        total = len(instances)

        active = 0
        for inst_data in instances.values():
            if is_window_active_in_session(session_name, inst_data.get("tmux_window_id")):
                active += 1

        tmux_status = "[green]Running[/green]" if tmux_session_exists(session_name) else "[dim]Not running[/dim]"
        table.add_row(session_name, str(total), str(active), tmux_status)

    console.print()
    console.print(table)
    console.print()


@session_app.command(name="rename")
def session_rename(
    old: Optional[str] = None,
    new: Optional[str] = None,
    *,
    common: CommonConfig,
) -> None:
    """Rename a ccmux session.

    Args:
        old: Current session name (or new name if only 1 arg given)
        new: New session name
        common: Common parameters (session, etc.)
    """
    if old is not None and new is not None:
        # Explicit: ccmux session rename <old> <new>
        old_name = old
        new_name = sanitize_name(new)
    elif old is not None and new is None:
        # 1 arg: rename current session to <new-name>
        new_name = sanitize_name(old)
        detected = detect_current_ccmux_session()
        if not detected:
            console.print("[red]Error:[/red] Not in a ccmux session.", style="bold")
            sys.exit(1)
        old_name = detected[0]
    elif old is None and new is None:
        # Interactive mode
        all_state = state.load_state()
        sessions = list(all_state.get("sessions", {}).keys())
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        console.print("\n[bold]Sessions:[/bold]")
        for i, s in enumerate(sessions):
            console.print(f"  {i + 1}. {s}")

        choice = Prompt.ask(
            "\nSelect session to rename",
            choices=[str(i + 1) for i in range(len(sessions))],
        )
        old_name = sessions[int(choice) - 1]
        raw_new = Prompt.ask("New name")
        new_name = sanitize_name(raw_new)
    else:
        console.print("[red]Error:[/red] Provide both old and new names, one name to rename current session, or run without args for interactive mode.", style="bold")
        sys.exit(1)

    if old_name == new_name:
        console.print(f"[yellow]Session is already named '{old_name}'.[/yellow]")
        return

    # Rename in state
    if not state.rename_session(old_name, new_name):
        # Check why it failed
        if not state.get_session(old_name):
            console.print(f"[red]Error:[/red] Session '{old_name}' not found.", style="bold")
        else:
            console.print(f"[red]Error:[/red] Session '{new_name}' already exists.", style="bold")
        sys.exit(1)

    # Rename tmux session if it exists
    if tmux_session_exists(old_name):
        try:
            subprocess.run(
                ["tmux", "rename-session", "-t", old_name, new_name],
                check=True, capture_output=True,
            )
            console.print(f"  [green]\u2713[/green] Renamed tmux session '{old_name}' -> '{new_name}'")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]\u26a0[/yellow] Could not rename tmux session (it may have been closed)")

    _notify_sidebars(new_name)
    console.print(f"\n[bold green]Success![/bold green] Session renamed: '{old_name}' -> '{new_name}'")


@session_app.command(name="activate")
def session_activate(
    name: Optional[str] = None,
    *,
    current: Annotated[bool, Parameter(name=["-c", "--current"], negative="")] = False,
    no_confirm: bool = False,
    common: CommonConfig,
) -> None:
    """Activate all inactive instances in a session.

    Args:
        name: Session name (overrides --session)
        current: Use the current tmux session
        no_confirm: Skip confirmation prompt
        common: Common parameters (session, etc.)
    """
    session = _resolve_session_name(name, current, common, allow_interactive=False)
    _activate_all_in_session(session, no_confirm)


@session_app.command(name="remove")
def session_remove(
    name: Optional[str] = None,
    *,
    current: Annotated[bool, Parameter(name=["-c", "--current"], negative="")] = False,
    no_confirm: bool = False,
    common: CommonConfig,
) -> None:
    """Remove an entire session and all its instances.

    Args:
        name: Session name to remove
        current: Remove the current tmux session
        no_confirm: Skip confirmation prompt
        common: Common parameters (session, etc.)
    """
    session = _resolve_session_name(name, current, common, allow_interactive=True)

    session_data = state.get_session(session)
    if not session_data:
        console.print(f"[red]Error:[/red] Session '{session}' not found.", style="bold")
        sys.exit(1)

    instances = session_data.get("instances", session_data.get("worktrees", {}))

    console.print(f"\n[bold red]Removing session '{session}' and all {len(instances)} instance(s)[/bold red]")
    console.print("[red]Worktree instances will be permanently deleted![/red]\n")

    for inst_name in instances:
        console.print(f"  \u2022 {inst_name}")
    console.print()

    if not no_confirm:
        if not Confirm.ask(f"[bold red]Permanently remove session '{session}'?[/bold red]", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Deactivate and remove each instance
    removed_count = 0
    for inst_name, inst_data in instances.items():
        tmux_window_id = inst_data.get("tmux_window_id")
        is_wt = inst_data.get("is_worktree", True)
        inst_path = Path(inst_data.get("instance_path", inst_data.get("worktree_path", "")))
        repo_path = Path(inst_data.get("repo_path", ""))

        # Kill tmux window if active
        if is_window_active_in_session(session, tmux_window_id):
            try:
                subprocess.run(
                    ["tmux", "kill-window", "-t", tmux_window_id],
                    check=True, capture_output=True,
                )
                console.print(f"  [green]\u2713[/green] Deactivated '{inst_name}'")
            except subprocess.CalledProcessError:
                pass

        # Remove git worktree if applicable
        if is_wt and worktree_exists(inst_path):
            try:
                subprocess.run(
                    ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(inst_path)],
                    check=True,
                )
                console.print(f"  [green]\u2713[/green] Removed git worktree '{inst_name}'")
            except subprocess.CalledProcessError as e:
                console.print(f"  [yellow]\u26a0[/yellow] Git worktree removal failed: {e}")
        elif not is_wt:
            console.print(f"  [dim]Main repository '{inst_name}' - no worktree to remove[/dim]")

        removed_count += 1

    # Kill the tmux session
    if tmux_session_exists(session):
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session],
                check=True, capture_output=True,
            )
            console.print(f"\n  [green]\u2713[/green] Killed tmux session '{session}'")
        except subprocess.CalledProcessError:
            console.print(f"\n  [yellow]\u26a0[/yellow] Could not kill tmux session '{session}'")

    # Remove session from state
    state.remove_session(session)

    console.print(f"\n[bold green]Success![/bold green] Removed session '{session}' ({removed_count} instance(s)).")


@session_app.command(name="attach")
def session_attach(*, common: CommonConfig) -> None:
    """Attach to a tmux session.

    Args:
        common: Common parameters (session, etc.)
    """
    session = common.session

    session_data = state.get_session(session)
    if session_data is None:
        console.print(f"[red]Error:[/red] ccmux session '{session}' not found.", style="bold")
        console.print(f"\nCreate an instance with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(1)

    if not tmux_session_exists(session):
        console.print(f"[red]Error:[/red] Tmux session no longer exists.", style="bold")
        console.print(f"\nThe tmux session was closed. Activate instances with: [cyan]ccmux activate --session {session}[/cyan]")
        sys.exit(1)

    _ensure_all_sidebars(session)
    _notify_sidebars(session)
    os.execvp("tmux", ["tmux", "attach", "-t", session])


# --- Instance Sub-App Commands ---

@app.default
def instance_info(*, common: CommonConfig) -> None:
    """Show current instance info, or help if none active."""
    detected = detect_current_ccmux_instance()
    if not detected:
        console.print("[yellow]Not currently in a ccmux instance.[/yellow]\n")
        app.help_print([])
        return

    session_name, instance_name, instance_data = detected
    _show_instance_info(session_name, instance_name, instance_data)


@app.command(name="which")
def instance_which() -> None:
    """Print the current instance name (useful for scripting)."""
    detected = detect_current_ccmux_instance()
    if detected is None:
        sys.exit(1)
    print(detected[1])


@app.command(name="new")
def instance_new(
    name: Optional[str] = None,
    *,
    worktree: Annotated[bool, Parameter(name=["-w", "--worktree"])] = False,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
    common: CommonConfig,
) -> None:
    """Create a new Claude Code instance in main repo or as a git worktree.

    Args:
        name: Name for the instance (generates random animal name if not provided)
        worktree: Create instance as a git worktree instead of using main repo
        yes: Skip confirmation prompts (auto-create as worktree if main exists)
        common: Common parameters (session, etc.)
    """
    session = common.session

    # Validate we're in a git repo
    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[red]Error:[/red] Not inside a git repository.", style="bold")
        sys.exit(1)

    os.chdir(repo_root)

    # Get default branch
    default_branch = get_default_branch()
    if default_branch is None:
        console.print("[red]Error:[/red] Could not detect default branch (main/master).", style="bold")
        sys.exit(1)

    # Check if creating a main repo instance when one already exists
    create_as_worktree = worktree
    instance_path = None

    if not worktree:
        existing_main = state.find_main_repo_instance(str(repo_root), session)
        if existing_main:
            console.print(f"[yellow]Warning:[/yellow] Main repository already has an instance: '{existing_main['name']}'")
            if yes or Confirm.ask("Create a worktree instead?", default=True):
                create_as_worktree = True
            else:
                console.print("[red]Aborted:[/red] Main repository already in use.")
                sys.exit(1)

    # Generate or sanitize name
    if name is None:
        for _ in range(20):
            candidate = sanitize_name(generate_animal_name())
            if create_as_worktree:
                test_path = repo_root / ".worktrees" / candidate
                if not worktree_exists(test_path):
                    name = candidate
                    break
            else:
                if not state.get_worktree(session, candidate):
                    name = candidate
                    break

        if name is None:
            base = sanitize_name(generate_animal_name())
            suffix = random.randint(10, 99)
            name = f"{base}-{suffix}"
    else:
        name = sanitize_name(name)

    # Set instance path based on type
    if create_as_worktree:
        instance_path = repo_root / ".worktrees" / name
        (repo_root / ".worktrees").mkdir(exist_ok=True)
    else:
        instance_path = repo_root

    # Create instance
    console.print(f"\n[bold cyan]Creating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Repo root: {repo_root}")
    if create_as_worktree:
        console.print(f"  Type:      Worktree")
        console.print(f"  Path:      {instance_path}")
        console.print(f"  Based on:  {default_branch} (detached)")
    else:
        console.print(f"  Type:      Main repository")
        console.print(f"  Path:      {instance_path}")

    # Create worktree if needed
    if create_as_worktree:
        try:
            if worktree_exists(instance_path):
                console.print("  [yellow]Worktree already exists, reusing it.[/yellow]")
            else:
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(instance_path), default_branch],
                    check=True,
                )
                console.print(f"  [green]\u2713[/green] Created detached worktree from {default_branch}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating worktree:[/red] {e}", style="bold")
            sys.exit(1)

        # Run post_create commands from ccmux.toml
        run_post_create(repo_root, instance_path, name, session)

    # Check if this is the first instance in the ccmux session
    session_data = state.get_session(session)
    is_first_instance = not tmux_session_exists(session)

    # Create or attach to tmux session
    instance_type = "worktree" if create_as_worktree else "main repo"
    launch_cmd = (
        f"echo 'Launching Claude Code in {instance_path} ({instance_type} instance: {name})'; "
        f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
    )

    tmux_window_id = None

    if is_first_instance:
        try:
            result = subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", session,
                    "-n", name,
                    "-c", str(instance_path),
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            console.print(f"  [green]\u2713[/green] Created tmux session '{session}' with window '{name}'")

            if apply_tmux_config(session):
                console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
            _add_sidebar_pane(session, tmux_window_id)
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
            sys.exit(1)
    else:
        try:
            result = subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", f"{session}",
                    "-n", name,
                    "-c", str(instance_path),
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _add_sidebar_pane(session, tmux_window_id)

            subprocess.run(
                ["tmux", "select-window", "-t", f"{session}:{name}"],
                check=True,
            )
            console.print(f"  [green]\u2713[/green] Created new window '{name}' in session '{session}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux window:[/red] {e}", style="bold")
            sys.exit(1)

    # Get tmux session ID and save to state
    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        state.add_worktree(
            session_name=session,
            worktree_name=name,
            repo_path=str(repo_root),
            worktree_path=str(instance_path),
            tmux_session_id=tmux_session_id,
            tmux_window_id=tmux_window_id,
            is_worktree=create_as_worktree
        )
    except subprocess.CalledProcessError:
        state.add_worktree(
            session_name=session,
            worktree_name=name,
            repo_path=str(repo_root),
            worktree_path=str(instance_path),
            is_worktree=create_as_worktree
        )

    console.print(f"  [green]\u2713[/green] Launched Claude Code in tmux window '{name}'")
    _notify_sidebars(session)

    # Auto-reactivate orphaned instances when a new session was just created
    if is_first_instance:
        existing_instances = state.get_all_worktrees(session)
        orphans = [
            inst for inst in existing_instances
            if inst["name"] != name
        ]

        if orphans:
            console.print(f"\n[bold cyan]Reactivating {len(orphans)} orphaned instance(s):[/bold cyan]")
            for inst in orphans:
                inst_name = inst["name"]
                inst_path = inst["instance_path"]
                inst_type = "worktree" if inst.get("is_worktree", True) else "main repo"

                reactivate_cmd = (
                    f"echo 'Reactivating Claude Code in {inst_path} ({inst_type} instance: {inst_name})'; "
                    f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
                )

                try:
                    result = subprocess.run(
                        [
                            "tmux", "new-window",
                            "-t", session,
                            "-n", inst_name,
                            "-c", inst_path,
                            "-P", "-F", "#{window_id}",
                            reactivate_cmd,
                        ],
                        capture_output=True, text=True, check=True,
                    )
                    new_window_id = result.stdout.strip()
                    _add_sidebar_pane(session, new_window_id)

                    try:
                        new_session_id = subprocess.run(
                            ["tmux", "display-message", "-t", session, "-p", "#{session_id}"],
                            capture_output=True, text=True, check=True,
                        ).stdout.strip()
                        state.update_tmux_ids(session, inst_name, new_session_id, new_window_id)
                    except subprocess.CalledProcessError:
                        pass

                    console.print(f"  [green]\u2713[/green] Reactivated '{inst_name}'")
                except subprocess.CalledProcessError as e:
                    console.print(f"  [yellow]\u26a0[/yellow] Could not reactivate '{inst_name}': {e}")

            # Select the user's newly-created window so they land on it
            try:
                subprocess.run(
                    ["tmux", "select-window", "-t", f"{session}:{name}"],
                    check=True, capture_output=True,
                )
            except subprocess.CalledProcessError:
                pass

    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")

    # Auto-attach if not already in tmux
    if "TMUX" not in os.environ:
        console.print()
        if Confirm.ask("Attach to tmux session now?", default=True):
            os.execvp("tmux", ["tmux", "attach", "-t", session])


@app.command(name="list")
def instance_list(
    *,
    common: CommonConfig,
    all_sessions: Annotated[bool, Parameter(negative="", alias="-a")] = False,
) -> None:
    """List all instances and their tmux session status.

    Args:
        common: Common parameters (session, etc.)
        all_sessions: List instances for all sessions
    """
    if all_sessions:
        all_state = state.load_state()
        sessions = all_state.get("sessions", {})

        if not sessions:
            console.print("\n[yellow]No sessions found.[/yellow]")
            console.print(f"Create one with: [cyan]ccmux new[/cyan]")
            return

        for session_name in sessions.keys():
            _display_session_table(session_name)
    else:
        session = common.session
        instances = state.get_all_worktrees(session)

        if not instances:
            console.print("\n[yellow]No instances found.[/yellow]")
            console.print(f"Create one with: [cyan]ccmux new[/cyan]")
            return

        _display_session_table(session)


@app.command(name="rename")
def instance_rename(
    old: Optional[str] = None,
    new: Optional[str] = None,
    *,
    common: CommonConfig,
) -> None:
    """Rename a ccmux instance.

    Args:
        old: Current instance name (or new name if only 1 arg given)
        new: New instance name
        common: Common parameters (session, etc.)
    """
    session = common.session

    if old is not None and new is not None:
        # Explicit: ccmux instance rename <old> <new>
        old_name = old
        new_name = sanitize_name(new)
        instance_data = state.get_worktree(session, old_name)
        if not instance_data:
            console.print(f"[red]Error:[/red] Instance '{old_name}' not found in session '{session}'.", style="bold")
            sys.exit(1)
    elif old is not None and new is None:
        # 1 arg: rename current instance to <new-name>
        new_name = sanitize_name(old)
        detected = detect_current_ccmux_instance()
        if not detected:
            console.print("[red]Error:[/red] Not in a ccmux instance.", style="bold")
            sys.exit(1)
        session = detected[0]
        old_name = detected[1]
        instance_data = detected[2]
    elif old is None and new is None:
        # Interactive mode
        instances = state.get_all_worktrees(session)
        if not instances:
            console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
            return

        console.print(f"\n[bold]Instances in session '{session}':[/bold]")
        for i, inst in enumerate(instances):
            console.print(f"  {i + 1}. {inst['name']}")

        choice = Prompt.ask(
            "\nSelect instance to rename",
            choices=[str(i + 1) for i in range(len(instances))],
        )
        old_name = instances[int(choice) - 1]["name"]
        instance_data = state.get_worktree(session, old_name)
        raw_new = Prompt.ask("New name")
        new_name = sanitize_name(raw_new)
    else:
        console.print("[red]Error:[/red] Provide both old and new names, one name to rename current instance, or run without args for interactive mode.", style="bold")
        sys.exit(1)

    if old_name == new_name:
        console.print(f"[yellow]Instance is already named '{old_name}'.[/yellow]")
        return

    # If it's a worktree, move the directory first (most likely to fail)
    is_wt = instance_data.get("is_worktree", True)
    if is_wt:
        old_path = Path(instance_data["instance_path"])
        repo_path = Path(instance_data["repo_path"])
        new_path = old_path.parent / new_name

        if old_path.exists():
            try:
                subprocess.run(
                    ["git", "-C", str(repo_path), "worktree", "move", str(old_path), str(new_path)],
                    check=True, capture_output=True, text=True,
                )
                console.print(f"  [green]\u2713[/green] Moved worktree directory: {old_path.name} -> {new_path.name}")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Error moving worktree:[/red] {e}", style="bold")
                sys.exit(1)

    # Rename in state
    if not state.rename_instance(session, old_name, new_name):
        if not state.get_worktree(session, old_name):
            console.print(f"[red]Error:[/red] Instance '{old_name}' not found.", style="bold")
        else:
            console.print(f"[red]Error:[/red] Instance '{new_name}' already exists.", style="bold")
        sys.exit(1)

    # Update instance_path in state if worktree was moved
    if is_wt:
        s = state.load_state()
        inst = s["sessions"][session]["instances"][new_name]
        inst["instance_path"] = str(new_path)
        state.save_state(s)

    # Rename tmux window if active
    tmux_window_id = instance_data.get("tmux_window_id")
    if tmux_window_id and is_window_active_in_session(session, tmux_window_id):
        try:
            subprocess.run(
                ["tmux", "rename-window", "-t", tmux_window_id, new_name],
                check=True, capture_output=True,
            )
            console.print(f"  [green]\u2713[/green] Renamed tmux window")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]\u26a0[/yellow] Could not rename tmux window")

    _notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Instance renamed: '{old_name}' -> '{new_name}'")


@app.command(name="activate")
def instance_activate(
    name: Optional[str] = None,
    *,
    common: CommonConfig,
    no_confirm: bool = False,
) -> None:
    """Activate Claude Code in an instance (useful if tmux window was closed).

    If no name is provided, activates all inactive instances in the session.

    Args:
        name: Instance name to activate (omit to activate all)
        common: Common parameters (session, etc.)
        no_confirm: Skip confirmation prompt (default: False)
    """
    session = common.session
    if name is None:
        _activate_all_in_session(session, no_confirm)
    else:
        _activate_single_instance(session, name, no_confirm)


@app.command(name="deactivate")
def instance_deactivate(
    name: Optional[str] = None,
    *,
    common: CommonConfig,
    no_confirm: bool = False,
) -> None:
    """Deactivate Claude Code instance(s) by killing tmux window (keeps instance).

    If no name is provided, deactivates all active instances in the session.

    Args:
        name: Instance name to deactivate (omit to deactivate all)
        common: Common parameters (session, etc.)
        no_confirm: Skip confirmation prompt (default: False)
    """
    session = common.session

    instances = state.get_all_worktrees(session)

    if not instances:
        console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
        sys.exit(0)

    # Check which instances are active (session-scoped)
    active_instances = []
    for inst in instances:
        if is_window_active_in_session(session, inst.get("tmux_window_id")):
            active_instances.append(inst)

    if name is None:
        if not active_instances:
            console.print(f"\n[yellow]No active instances to deactivate in session '{session}'.[/yellow]")
            return

        console.print(f"\n[bold yellow]Deactivating {len(active_instances)} active instance(s) in session '{session}':[/bold yellow]")
        for inst in active_instances:
            console.print(f"  \u2022 {inst['name']}")
        console.print()

        if not no_confirm:
            if not Confirm.ask(f"Deactivate all {len(active_instances)} instance(s)?", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        deactivated_count = 0
        for inst in active_instances:
            inst_name = inst["name"]
            tmux_window_id = inst.get("tmux_window_id")
            if tmux_window_id:
                try:
                    subprocess.run(
                        ["tmux", "kill-window", "-t", tmux_window_id],
                        check=True, capture_output=True,
                    )
                    console.print(f"  [green]\u2713[/green] Deactivated '{inst_name}'")
                    deactivated_count += 1
                except subprocess.CalledProcessError:
                    console.print(f"  [yellow]Window '{inst_name}' not found or already closed[/yellow]")

        _notify_sidebars(session)
        console.print(f"\n[bold green]Success![/bold green] Deactivated {deactivated_count} instance(s).")
        return

    # Deactivate single instance
    instance = None
    for inst in instances:
        if inst["name"] == name:
            instance = inst
            break

    if instance is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found in session '{session}'.", style="bold")
        sys.exit(1)

    if instance not in active_instances:
        console.print(f"[yellow]Instance '{name}' is already inactive.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating instance '{name}' in session '{session}'[/bold yellow]")

    tmux_window_id = instance.get("tmux_window_id")
    if tmux_window_id:
        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", tmux_window_id],
                check=True, capture_output=True,
            )
            console.print(f"  [green]\u2713[/green] Deactivated '{name}'")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]Window '{name}' not found or already closed[/yellow]")

    _notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Instance '{name}' deactivated.")


@app.command(name="remove")
def instance_remove(
    name: Optional[str] = None,
    *,
    common: CommonConfig,
    no_confirm: bool = False,
) -> None:
    """Remove instance(s) permanently (deactivates and deletes worktree).

    If no name is provided, removes all instances in the session.

    Args:
        name: Instance name to remove (omit to remove all)
        common: Common parameters (session, etc.)
        no_confirm: Skip confirmation prompt (default: False)
    """
    session = common.session

    worktrees = state.get_all_worktrees(session)

    if not worktrees:
        console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
        sys.exit(0)

    # Check which are active
    active_worktrees = []
    inactive_worktrees = []
    for wt in worktrees:
        if is_window_active_in_session(session, wt.get("tmux_window_id")):
            active_worktrees.append(wt)
        else:
            inactive_worktrees.append(wt)

    if name is None:
        console.print(f"\n[bold red]WARNING: This will permanently delete {len(worktrees)} instance(s) in session '{session}'[/bold red]")
        console.print("[red]Any uncommitted changes will be lost![/red]\n")

        if active_worktrees:
            console.print(f"  Active ({len(active_worktrees)}):")
            for wt in active_worktrees:
                console.print(f"    \u2022 {wt['name']}")
        if inactive_worktrees:
            console.print(f"  Inactive ({len(inactive_worktrees)}):")
            for wt in inactive_worktrees:
                console.print(f"    \u2022 {wt['name']}")
        console.print()

        if not no_confirm:
            if not Confirm.ask(f"[bold red]Permanently remove all {len(worktrees)} instance(s)?[/bold red]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        removed_count = 0
        for wt in worktrees:
            wt_name = wt["name"]
            wt_path = Path(wt["instance_path"])
            is_active = wt in active_worktrees
            is_main_repo = not wt.get("is_worktree", True)

            if is_active:
                tmux_window_id = wt.get("tmux_window_id")
                if tmux_window_id:
                    try:
                        subprocess.run(
                            ["tmux", "kill-window", "-t", tmux_window_id],
                            check=True, capture_output=True,
                        )
                        console.print(f"  [green]\u2713[/green] Deactivated '{wt_name}'")
                    except subprocess.CalledProcessError:
                        console.print(f"  [yellow]Window '{wt_name}' already closed[/yellow]")

            prefix = "    " if is_active else "  "

            if is_main_repo:
                console.print(f"{prefix}[dim]Main repository - no git worktree to remove[/dim]")
            elif worktree_exists(wt_path):
                try:
                    repo_path = Path(wt["repo_path"])
                    subprocess.run(
                        ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(wt_path)],
                        check=True,
                    )
                    console.print(f"{prefix}[green]\u2713[/green] Removed git worktree '{wt_name}'")
                except subprocess.CalledProcessError as e:
                    console.print(f"{prefix}[yellow]\u26a0[/yellow] Git worktree removal failed: {e}")
                    console.print(f"{prefix}  [dim]Will remove from tracking anyway...[/dim]")
            else:
                console.print(f"{prefix}[yellow]\u26a0[/yellow] Worktree not found on filesystem")

            state.remove_worktree(session, wt_name)
            console.print(f"{prefix}[green]\u2713[/green] Removed '{wt_name}' from tracking")
            removed_count += 1

        # Kill the entire tmux session if it exists
        if tmux_session_exists(session):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", session],
                    check=True, capture_output=True,
                )
                console.print(f"\n[green]\u2713[/green] Killed tmux session '{session}'")
            except subprocess.CalledProcessError:
                console.print(f"\n[yellow]\u26a0[/yellow] Could not kill tmux session '{session}'")

        console.print(f"\n[bold green]Success![/bold green] Removed {removed_count} instance(s).")
        return

    # Remove single instance
    worktree = None
    for wt in worktrees:
        if wt["name"] == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found in session '{session}'.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list --session {session}[/cyan]")
        sys.exit(1)

    wt_path = Path(worktree["instance_path"])
    is_active = worktree in active_worktrees
    is_main_repo = not worktree.get("is_worktree", True)

    if is_main_repo:
        console.print(f"\n[bold red]WARNING: Removing main repository '{name}' from tracking[/bold red]")
        console.print("[yellow]This will only remove it from ccmux tracking, not delete the repository itself.[/yellow]")
    else:
        console.print(f"\n[bold red]WARNING: Removing instance '{name}' from session '{session}'[/bold red]")
        console.print("[red]This will permanently delete the worktree and any uncommitted changes![/red]")

    console.print(f"  Path: {wt_path}")
    console.print(f"  Status: {'Active' if is_active else 'Inactive'}\n")

    if not no_confirm:
        prompt = f"[bold red]Remove '{name}' from tracking?[/bold red]" if is_main_repo else f"[bold red]Permanently remove instance '{name}'?[/bold red]"
        if not Confirm.ask(prompt, default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    if is_active:
        tmux_window_id = worktree.get("tmux_window_id")
        if tmux_window_id:
            try:
                subprocess.run(
                    ["tmux", "kill-window", "-t", tmux_window_id],
                    check=True, capture_output=True,
                )
                console.print(f"  [green]\u2713[/green] Deactivated '{name}'")
            except subprocess.CalledProcessError:
                console.print(f"  [yellow]Window '{name}' already closed[/yellow]")

    if is_main_repo:
        console.print(f"  [dim]Main repository - no git worktree to remove[/dim]")
    elif worktree_exists(wt_path):
        try:
            repo_path = Path(worktree["repo_path"])
            subprocess.run(
                ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(wt_path)],
                check=True,
            )
            console.print(f"  [green]\u2713[/green] Removed git worktree at {wt_path}")
        except subprocess.CalledProcessError as e:
            console.print(f"  [yellow]\u26a0[/yellow] Git worktree removal failed: {e}")
            console.print(f"    [dim]Will remove from tracking anyway...[/dim]")
    else:
        console.print(f"  [yellow]\u26a0[/yellow] Worktree not found on filesystem")

    state.remove_worktree(session, name)
    _notify_sidebars(session)
    console.print(f"  [green]\u2713[/green] Removed '{name}' from tracking")

    if is_main_repo:
        console.print(f"\n[bold green]Success![/bold green] Main repository '{name}' removed from tracking.")
    else:
        console.print(f"\n[bold green]Success![/bold green] Instance '{name}' removed.")


# --- Top-Level Commands ---

@app.command
def export_tmux_config(
    *,
    output: Optional[Path] = None,
) -> None:
    """Export the ccmux tmux configuration to a file.

    This exports the tmux configuration that ccmux applies to its sessions.
    You can use this to apply the same configuration globally or to customize it.

    Args:
        output: Output file path. If not specified, prints to stdout.
    """
    from ccmux.tmux_config import get_tmux_config_content

    content = get_tmux_config_content()

    if output:
        try:
            if output.exists():
                if not Confirm.ask(f"[yellow]File {output} exists. Overwrite?[/yellow]", default=False):
                    console.print("[yellow]Cancelled.[/yellow]")
                    return

            output.write_text(content)
            console.print(f"[green]\u2713[/green] Exported tmux configuration to {output}")
        except Exception as e:
            console.print(f"[red]Error writing file:[/red] {e}", style="bold")
            sys.exit(1)
    else:
        console.print(content)


# --- Sidebar Sub-App Commands ---

@sidebar_app.command(name="reload")
def sidebar_reload(
    *,
    all_windows: Annotated[bool, Parameter(negative="", alias="-a")] = False,
    common: CommonConfig,
) -> None:
    """Reload sidebar pane(s) (kill and restart).

    By default reloads the sidebar for the current tmux window.
    Use --all to reload sidebars for all windows in the session.

    Args:
        all_windows: Reload sidebars for all windows in the session
        common: Common parameters (session, etc.)
    """
    if "TMUX" not in os.environ and not all_windows:
        console.print("[red]Error:[/red] Not inside tmux. Use --all to reload all sidebars.", style="bold")
        sys.exit(1)

    session = common.session

    if all_windows:
        instances = state.get_all_worktrees(session)
        if not instances:
            console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
            return

        reloaded = 0
        for inst in instances:
            window_id = inst.get("tmux_window_id")
            if window_id and is_window_active_in_session(session, window_id):
                _reload_sidebar_pane(session, window_id)
                console.print(f"  [green]\u2713[/green] Reloaded sidebar for '{inst['name']}'")
                reloaded += 1

        if reloaded:
            console.print(f"\n[bold green]Success![/bold green] Reloaded {reloaded} sidebar(s).")
        else:
            console.print("[yellow]No active windows found.[/yellow]")
        return

    # Single window: detect current window
    try:
        window_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        console.print("[red]Error:[/red] Could not determine current tmux window.", style="bold")
        sys.exit(1)

    _reload_sidebar_pane(session, window_id)
    console.print("[green]\u2713[/green] Sidebar reloaded.")


# --- Meta (parameter injection + alias rewriting) ---

@app.meta.default
def meta(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    session: Annotated[str, Parameter(negative="", alias="-s")] = DEFAULT_SESSION,
):
    """Meta command to inject common parameters into subcommands.

    Args:
        tokens: Command tokens to parse
        session: ccmux session name
    """
    common = Common(session=session)

    # Rewrite top-level aliases to sub-app paths
    if tokens and tokens[0] in TOP_LEVEL_ALIASES:
        tokens = tuple(TOP_LEVEL_ALIASES[tokens[0]]) + tokens[1:]

    command, bound, _ = app.parse_args(tokens)

    # Check if the command accepts the common parameter
    sig = inspect.signature(command)
    if "common" in sig.parameters:
        return command(*bound.args, **bound.kwargs, common=common)
    else:
        return command(*bound.args, **bound.kwargs)


def main():
    """Main entry point for the CLI."""
    try:
        app.meta()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
