#!/usr/bin/env python3
"""Claude Code Multiplexer CLI - Manage multiple Claude Code instances."""

import os
import random
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from cyclopts import Parameter
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ccmux import state
from ccmux.config import run_post_create
from ccmux.ui.tmux import apply_outer_session_config, apply_tmux_config

# Default session name
DEFAULT_SESSION = "default"

# Outer session pane dimensions
SIDEBAR_WIDTH = 41   # 4 chars wider than 37-char CCMUX ASCII art title
BASH_PANE_HEIGHT = 4


console = Console()
app = cyclopts.App(
    name="ccmux",
    help="Claude Code Multiplexer - Manage multiple Claude Code instances.",
)


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
    """Get the main git repository root directory.

    Uses --git-common-dir to resolve through linked worktrees to the main repo,
    so this always returns the root of the main worktree even when called from
    inside a linked worktree.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        # --git-common-dir returns the .git directory of the main repo
        # (e.g., /repo/.git), so the parent is the repo root
        git_common_dir = Path(result.stdout.strip())
        return git_common_dir.parent
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


def worktree_exists(worktree_path: Path, repo_path: Path | None = None) -> bool:
    """Check if a worktree exists and is registered."""
    try:
        cmd = ["git"]
        if repo_path:
            cmd += ["-C", str(repo_path)]
        cmd += ["worktree", "list"]
        result = subprocess.run(
            cmd,
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
            ["tmux", "has-session", "-t", f"={session_name}"],
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


# --- Session Name Helpers ---

def _inner_session_name(session: str) -> str:
    """Derive the inner tmux session name."""
    return f"{session}-inner"


def _ccmux_session_from_tmux(tmux_session_name: str) -> str:
    """Strip '-inner' or '-bash' suffix to get the ccmux session name.

    Also reverses the _outer_session_name() mapping:
      'ccmux' -> DEFAULT_SESSION, 'ccmux-foo' -> 'foo'.
    """
    if tmux_session_name.endswith("-inner"):
        return tmux_session_name[:-6]
    if tmux_session_name.endswith("-bash"):
        return tmux_session_name[:-5]
    if tmux_session_name == "ccmux":
        return DEFAULT_SESSION
    if tmux_session_name.startswith("ccmux-"):
        return tmux_session_name[6:]
    return tmux_session_name


def is_instance_window_active(session: str, tmux_window_id: Optional[str]) -> bool:
    """Check if an instance window is active (checks inner session)."""
    return is_window_active_in_session(_inner_session_name(session), tmux_window_id)


# --- Sidebar Helpers ---

from ccmux.ui.sidebar.process_id import SIDEBAR_PIDS_DIR  # noqa: E402
HOOKS_DIR = Path.home() / ".ccmux" / "hooks"


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


def _bash_session_name(session: str) -> str:
    """Derive the bash tmux session name."""
    return f"{session}-bash"


def _outer_session_name(session: str) -> str:
    """Derive the outer tmux session name."""
    if session == DEFAULT_SESSION:
        return "ccmux"
    return f"ccmux-{session}"


def _create_bash_window(session: str, instance_name: str, working_dir: str) -> None:
    """Create a window in the bash session for an instance.

    Creates the bash session if it doesn't exist yet.
    Skips if window already exists.
    """
    bash = _bash_session_name(session)
    bash_cmd = (
        f"export CCMUX_INSTANCE={instance_name}; "
        f"while true; do $SHELL; done"
    )
    try:
        if not tmux_session_exists(bash):
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", bash,
                 "-n", instance_name, "-c", working_dir,
                 bash_cmd],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["tmux", "set-option", "-t", bash, "status", "off"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["tmux", "set-option", "-t", bash, "mouse", "on"],
                check=True, capture_output=True,
            )
        else:
            if instance_name in get_tmux_windows(bash):
                return
            subprocess.run(
                ["tmux", "new-window", "-t", bash,
                 "-n", instance_name, "-c", working_dir,
                 bash_cmd],
                check=True, capture_output=True,
            )
        # Set background on the newly created window (window-level option)
        subprocess.run(
            ["tmux", "set-option", "-w", "-t", f"{bash}:{instance_name}",
             "window-style", "bg=#1e1e1e"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass


def _create_outer_session(session: str) -> None:
    """Create the outer tmux session with sidebar, inner client, and bash pane.

    The outer session has three panes:
    - Top-left (44 chars): sidebar TUI
    - Top-right (remainder): nested tmux client attached to the inner session
    - Bottom (full width, 4 rows): nested tmux client attached to bash session

    Skips if outer already exists or inner doesn't exist.
    """
    inner = _inner_session_name(session)
    bash = _bash_session_name(session)
    outer = _outer_session_name(session)

    if tmux_session_exists(outer):
        return
    if not tmux_session_exists(inner):
        return

    python_exe = sys.executable or "python3"
    sidebar_cmd = (
        f"TERM=tmux-256color COLORTERM=truecolor {python_exe} -m ccmux.ui.sidebar {session} ; "
        f"echo 'Sidebar exited. Press enter to close.' ; read"
    )

    try:
        # 1. Create outer session with sidebar as the initial pane (full screen)
        subprocess.run(
            [
                "tmux", "new-session",
                "-d",
                "-s", outer,
                sidebar_cmd,
            ],
            check=True,
            capture_output=True,
        )

        # 2. Split full-width bottom pane for bash
        if tmux_session_exists(bash):
            subprocess.run(
                [
                    "tmux", "split-window",
                    "-t", f"{outer}:0.0",
                    "-v", "-l", str(BASH_PANE_HEIGHT),
                    f"TMUX= tmux attach -t ={bash}",
                ],
                check=True,
                capture_output=True,
            )
        # Now: pane 0 = sidebar (top), pane 1 = bash (bottom)

        # 3. Split top pane horizontally for inner client
        subprocess.run(
            [
                "tmux", "split-window",
                "-t", f"{outer}:0.0",
                "-h", "-l", "50%",
                f"TMUX= tmux attach -t ={inner}",
            ],
            check=True,
            capture_output=True,
        )
        # Now: pane 0 = sidebar (top-left), pane 1 = inner (top-right), pane 2 = bash (bottom full width)

        # Apply outer session config (no status bar, C-Space prefix, etc.)
        apply_outer_session_config(outer)

        # Install client-resized hook to enforce fixed pane sizes on attach/resize
        resize_cmd = f"resize-pane -t {outer}:0.0 -x {SIDEBAR_WIDTH}"
        if tmux_session_exists(bash):
            resize_cmd += f" ; resize-pane -t {outer}:0.2 -y {BASH_PANE_HEIGHT}"
        subprocess.run(
            ["tmux", "set-hook", "-t", outer, "client-resized", resize_cmd],
            check=True, capture_output=True,
        )

        # Install hook on inner session for sidebar refresh + bash sync
        _install_inner_hook(session)

    except subprocess.CalledProcessError as exc:
        print(
            f"ccmux: failed to create outer session '{outer}': {exc}\n"
            f"  stderr: {exc.stderr.decode() if exc.stderr else '(none)'}",
            file=sys.stderr,
        )


def _ensure_outer_session(session: str) -> None:
    """Ensure the outer session exists; create if missing.

    If inner doesn't exist, returns early.
    If outer exists, just ensures the inner hook is installed.
    Otherwise, creates the outer session.
    """
    inner = _inner_session_name(session)
    if not tmux_session_exists(inner):
        return

    if tmux_session_exists(_outer_session_name(session)):
        _install_inner_hook(session)
        return

    _create_outer_session(session)


def _kill_outer_session(session: str) -> bool:
    """Kill the outer tmux session and its associated bash session.

    Returns True if the outer session was killed.
    """
    # Also kill the bash session if it exists
    bash = _bash_session_name(session)
    if tmux_session_exists(bash):
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", f"={bash}"],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass

    outer = _outer_session_name(session)
    if not tmux_session_exists(outer):
        return False

    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", f"={outer}"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _install_inner_hook(session: str) -> None:
    """Install hooks on the inner session for sidebar refresh, bell tracking, and bash sync.

    Registers two hooks:
    - alert-bell: sets @ccmux_bell 1 on the triggering window, then notifies sidebars
    - after-select-window: clears @ccmux_bell 0, switches bash window, then notifies sidebars
    """
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    script_path = HOOKS_DIR / f"notify-sidebar-{session}.sh"

    inner = _inner_session_name(session)
    bash = _bash_session_name(session)

    script_content = f"""\
#!/bin/sh
WIN=$(tmux display-message -t "{inner}" -p '#{{window_name}}' 2>/dev/null)
if [ -n "$WIN" ]; then
    if ! tmux select-window -t "{bash}:$WIN" 2>/dev/null; then
        # Bash window missing — recreate it
        DIR=$(tmux display-message -t "{inner}" -p '#{{pane_current_path}}' 2>/dev/null)
        [ -z "$DIR" ] && DIR="$HOME"
        tmux new-window -t "{bash}" -n "$WIN" -c "$DIR" \
            "export CCMUX_INSTANCE=$WIN; while true; do \\$SHELL; done" 2>/dev/null
        tmux set-option -w -t "{bash}:$WIN" window-style 'bg=#1e1e1e' 2>/dev/null
        tmux select-window -t "{bash}:$WIN" 2>/dev/null
    fi
fi
# Notify sidebar processes
for f in "$HOME/.ccmux/sidebar_pids/{session}"/*.pid; do
    [ -f "$f" ] && kill -USR1 "$(cat "$f")" 2>/dev/null
done
"""
    script_path.write_text(script_content)
    script_path.chmod(0o755)

    inner = _inner_session_name(session)

    # alert-bell: persist the bell flag and notify sidebars
    try:
        subprocess.run(
            ["tmux", "set-hook", "-t", inner,
             "alert-bell",
             f"set -w @ccmux_bell 1 ; run-shell '{script_path}'"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass

    # after-select-window: clear the bell flag and notify sidebars
    try:
        subprocess.run(
            ["tmux", "set-hook", "-t", inner,
             "after-select-window",
             f"set -w @ccmux_bell 0 ; run-shell '{script_path}'"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass


def _uninstall_inner_hook(session: str) -> None:
    """Remove the alert-bell and after-select-window hooks from the inner session."""
    inner = _inner_session_name(session)
    for hook_name in ("alert-bell", "after-select-window"):
        try:
            subprocess.run(
                ["tmux", "set-hook", "-u", "-t", inner, hook_name],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass

    script_path = HOOKS_DIR / f"notify-sidebar-{session}.sh"
    try:
        script_path.unlink(missing_ok=True)
    except OSError:
        pass


# --- Detection Helpers ---

def detect_current_ccmux_instance() -> Optional[tuple[str, str, "state.Instance"]]:
    """Detect the current ccmux instance.

    Checks CCMUX_INSTANCE env var first (set in each pane),
    then falls back to tmux ID matching for backward compat.

    Returns (session_name, instance_name, Instance) or None.
    """
    # Fast path: env var set by ccmux in every pane
    env_name = os.environ.get("CCMUX_INSTANCE")
    if env_name:
        inst = state.get_instance(env_name, DEFAULT_SESSION)
        if inst:
            return (DEFAULT_SESSION, env_name, inst)

    # Fallback: tmux ID matching (backward compat for pre-env-var panes)
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

    return state.find_instance_by_tmux_ids(tmux_session_id, tmux_window_id)


def detect_current_ccmux_instance_any() -> Optional[tuple[str, str, "state.Instance"]]:
    """Detect the current ccmux instance from inner or bash session.

    First tries detect_current_ccmux_instance (env var + inner-session tmux IDs).
    Falls back to bash-session detection: uses the tmux session name
    (e.g. 'default-bash') and window name (= instance name) to look up
    the instance in state.

    Returns (session_name, instance_name, Instance) or None.
    """
    result = detect_current_ccmux_instance()
    if result:
        return result

    # Try bash-session detection
    tmux_session = get_current_tmux_session()
    if tmux_session and tmux_session.endswith("-bash"):
        ccmux_session = _ccmux_session_from_tmux(tmux_session)
        window_name = get_current_tmux_window()
        if window_name:
            instance_data = state.get_instance(window_name, ccmux_session)
            if instance_data:
                return (ccmux_session, window_name, instance_data)

    # Final fallback: match cwd against known instance paths
    try:
        cwd = str(Path.cwd().resolve())
    except OSError:
        return None
    result = state.find_instance_by_path(cwd, DEFAULT_SESSION)
    if result:
        return (DEFAULT_SESSION, result[0], result[1])
    return None


# --- Internal Helpers ---

def _display_session_table(session: str) -> None:
    """Display a table of instances.

    Args:
        session: Session name to display
    """
    instances = state.get_all_instances(session)

    if not instances:
        console.print(f"\n[yellow]No instances found.[/yellow]")
        return

    # Create Rich table
    table = Table(title="Claude Code Instances", show_header=True)
    table.add_column("Repository", style="yellow")
    table.add_column("Instance", style="cyan", no_wrap=True)
    table.add_column("Type", style="green")
    table.add_column("Branch")
    table.add_column("Status", style="bold")
    table.add_column("Tmux Window", style="blue")
    table.add_column("Path", style="dim")

    active_count = 0
    for inst in instances:
        name = inst.name
        repo_path = Path(inst.repo_path)
        instance_path = Path(inst.instance_path)
        tmux_window_id = inst.tmux_window_id
        is_worktree = inst.is_worktree

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

        # Get tmux window name and check if active (checks inner session)
        tmux_window_name = ""
        status = "[dim]\u25cb Inactive[/dim]"
        if is_instance_window_active(session, tmux_window_id):
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


def _show_instance_info(session_name: str, instance_name: str, instance_data) -> None:
    """Display info about a specific instance."""
    repo_path = Path(instance_data.repo_path)
    repo_name = repo_path.name
    worktree_path = Path(instance_data.instance_path)
    is_worktree = instance_data.is_worktree

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
    console.print(f"[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[bold cyan]Type:[/bold cyan]       {'worktree' if is_worktree else 'main repo'}")
    console.print(f"[bold cyan]Branch:[/bold cyan]     {branch}")
    console.print(f"[bold cyan]Path:[/bold cyan]       {worktree_path}\n")


def _activate_all_in_session(session: str, yes: bool = False) -> None:
    """Activate all inactive instances in a session."""
    worktrees = state.get_all_instances(session)

    if not worktrees:
        console.print(f"[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        sys.exit(0)

    # Check which are inactive (checks inner session)
    inactive_worktrees = []
    for wt in worktrees:
        if not is_instance_window_active(session, wt.tmux_window_id):
            inactive_worktrees.append(wt)

    if not inactive_worktrees:
        _ensure_outer_session(session)
        console.print("\n[yellow]No inactive instances to activate.[/yellow]")
        return

    console.print(f"\n[bold cyan]Found {len(inactive_worktrees)} inactive instance(s):[/bold cyan]")
    for wt in inactive_worktrees:
        console.print(f"  \u2022 {wt.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"Activate all {len(inactive_worktrees)} instance(s)?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    inner = _inner_session_name(session)
    inner_exists_flag = tmux_session_exists(inner)

    activated_count = 0
    for i, wt in enumerate(inactive_worktrees):
        wt_name = wt.name
        wt_path = wt.instance_path

        launch_cmd = (
            f"export CCMUX_INSTANCE={wt_name}; "
            f"echo 'Activating Claude Code in {wt_path}'; "
            f"unset CLAUDECODE; "
            f"claude; while true; do $SHELL; done"
        )

        try:
            new_tmux_window_id = None

            if not inner_exists_flag and i == 0:
                result = subprocess.run(
                    [
                        "tmux", "new-session",
                        "-d",
                        "-s", inner,
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
                _create_bash_window(session, wt_name, wt_path)
                inner_exists_flag = True
                console.print(f"  [green]\u2713[/green] Created tmux session and activated '{wt_name}'")

                if apply_tmux_config(inner):
                    console.print(f"    [green]\u2713[/green] Applied ccmux tmux configuration")
                else:
                    console.print(f"    [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
                _create_outer_session(session)
            else:
                result = subprocess.run(
                    [
                        "tmux", "new-window",
                        "-t", inner,
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
                _create_bash_window(session, wt_name, wt_path)
                console.print(f"  [green]\u2713[/green] Activated '{wt_name}'")

            # Update tmux IDs in state
            try:
                new_tmux_session_id = subprocess.run(
                    ["tmux", "display-message", "-t", inner, "-p", "#{session_id}"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()
                state.update_tmux_ids(wt_name, session, new_tmux_session_id, new_tmux_window_id)
            except subprocess.CalledProcessError:
                pass

            activated_count += 1
        except subprocess.CalledProcessError as e:
            console.print(f"  [red]Error activating '{wt_name}':[/red] {e}")

    _ensure_outer_session(session)
    _notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Activated {activated_count} instance(s).")


def _activate_single_instance(session: str, name: str, yes: bool = False) -> None:
    """Activate a single instance by name."""
    worktrees = state.get_all_instances(session)

    if not worktrees:
        console.print(f"[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        sys.exit(0)

    # Find the instance
    worktree = None
    for wt in worktrees:
        if wt.name == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list[/cyan]")
        sys.exit(1)

    # Check if already active - ensure outer session even if window exists
    if is_instance_window_active(session, worktree.tmux_window_id):
        _ensure_outer_session(session)
        console.print(f"[yellow]Instance '{name}' already has an active tmux window.[/yellow]")
        return

    wt_path = worktree.instance_path

    console.print(f"\n[bold cyan]Activating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Instance: {wt_path}")

    inner = _inner_session_name(session)
    inner_exists_flag = tmux_session_exists(inner)

    launch_cmd = (
        f"export CCMUX_INSTANCE={name}; "
        f"echo 'Activating Claude Code in {wt_path}'; "
        f"unset CLAUDECODE; "
        f"claude; while true; do $SHELL; done"
    )

    try:
        tmux_window_id = None

        if not inner_exists_flag:
            result = subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", inner,
                    "-n", name,
                    "-c", wt_path,
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _create_bash_window(session, name, wt_path)
            console.print(f"  [green]\u2713[/green] Created tmux session and activated '{name}'")

            if apply_tmux_config(inner):
                console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
            _create_outer_session(session)
        else:
            result = subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", inner,
                    "-n", name,
                    "-c", wt_path,
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _create_bash_window(session, name, wt_path)

            subprocess.run(
                ["tmux", "select-window", "-t", f"{inner}:{name}"],
                check=True,
            )
            console.print(f"  [green]\u2713[/green] Activated '{name}'")

        # Update tmux IDs in state
        try:
            tmux_session_id = subprocess.run(
                ["tmux", "display-message", "-t", inner, "-p", "#{session_id}"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            state.update_tmux_ids(name, session, tmux_session_id, tmux_window_id)
        except subprocess.CalledProcessError:
            pass

        _ensure_outer_session(session)
        _notify_sidebars(session)
        console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
        console.print(f"Attach with: [cyan]ccmux attach[/cyan]")

        # Auto-attach if not already in tmux
        if "TMUX" not in os.environ:
            console.print()
            if yes or Confirm.ask("Attach to tmux session now?", default=True):
                os.execvp("tmux", ["tmux", "attach", "-t", f"={_outer_session_name(session)}"])

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error activating Claude Code:[/red] {e}", style="bold")
        sys.exit(1)


# --- Instance Commands ---

@app.default
def instance_info() -> None:
    """Show current instance info, or help if none active."""
    detected = detect_current_ccmux_instance_any()
    if not detected:
        console.print("[yellow]Not currently in a ccmux instance.[/yellow]\n")
        app.help_print([])
        return

    session_name, instance_name, instance_data = detected
    _show_instance_info(session_name, instance_name, instance_data)


@app.command(name="which")
def instance_which() -> None:
    """Print the current instance name (useful for scripting)."""
    detected = detect_current_ccmux_instance_any()
    if detected is None:
        sys.exit(1)
    print(detected[1])


@app.command(name="new")
def instance_new(
    name: Optional[str] = None,
    *,
    worktree: Annotated[bool, Parameter(name=["-w", "--worktree"])] = False,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Create a new Claude Code instance in main repo or as a git worktree.

    Args:
        name: Name for the instance (generates random animal name if not provided)
        worktree: Create instance as a git worktree instead of using main repo
        yes: Skip confirmation prompts (auto-create as worktree if main exists)
    """
    session = DEFAULT_SESSION

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
            console.print(f"[yellow]Warning:[/yellow] Main repository already has an instance: '{existing_main.name}'")
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
                if not worktree_exists(test_path, repo_root):
                    name = candidate
                    break
            else:
                if not state.get_instance(candidate, session):
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
            if worktree_exists(instance_path, repo_root):
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
    inner = _inner_session_name(session)
    session_data = state.get_session(session)
    is_first_instance = not tmux_session_exists(inner)

    # Create or attach to tmux session
    instance_type = "worktree" if create_as_worktree else "main repo"
    launch_cmd = (
        f"export CCMUX_INSTANCE={name}; "
        f"echo 'Launching Claude Code in {instance_path} ({instance_type} instance: {name})'; "
        f"unset CLAUDECODE; "
        f"claude; while true; do $SHELL; done"
    )

    tmux_window_id = None

    if is_first_instance:
        try:
            result = subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", inner,
                    "-n", name,
                    "-c", str(instance_path),
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _create_bash_window(session, name, str(instance_path))
            console.print(f"  [green]\u2713[/green] Created tmux session '{inner}' with window '{name}'")

            if apply_tmux_config(inner):
                console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
            _create_outer_session(session)
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
            sys.exit(1)
    else:
        try:
            result = subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", inner,
                    "-n", name,
                    "-c", str(instance_path),
                    "-P", "-F", "#{window_id}",
                    launch_cmd,
                ],
                capture_output=True, text=True, check=True,
            )
            tmux_window_id = result.stdout.strip()
            _create_bash_window(session, name, str(instance_path))

            subprocess.run(
                ["tmux", "select-window", "-t", f"{inner}:{name}"],
                check=True,
            )
            console.print(f"  [green]\u2713[/green] Created new window '{name}' in session '{session}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux window:[/red] {e}", style="bold")
            sys.exit(1)

    # Get tmux session ID and save to state
    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-t", inner, "-p", "#{session_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        state.add_instance(
            session_name=session,
            instance_name=name,
            repo_path=str(repo_root),
            instance_path=str(instance_path),
            tmux_session_id=tmux_session_id,
            tmux_window_id=tmux_window_id,
            is_worktree=create_as_worktree
        )
    except subprocess.CalledProcessError:
        state.add_instance(
            session_name=session,
            instance_name=name,
            repo_path=str(repo_root),
            instance_path=str(instance_path),
            is_worktree=create_as_worktree
        )

    console.print(f"  [green]\u2713[/green] Launched Claude Code in tmux window '{name}'")
    _notify_sidebars(session)

    # Auto-reactivate orphaned instances when a new session was just created
    if is_first_instance:
        existing_instances = state.get_all_instances(session)
        orphans = [
            inst for inst in existing_instances
            if inst.name != name
        ]

        if orphans:
            console.print(f"\n[bold cyan]Reactivating {len(orphans)} orphaned instance(s):[/bold cyan]")
            for inst in orphans:
                inst_name = inst.name
                inst_path = inst.instance_path
                inst_type = inst.instance_type + " repo" if not inst.is_worktree else "worktree"

                reactivate_cmd = (
                    f"export CCMUX_INSTANCE={inst_name}; "
                    f"echo 'Reactivating Claude Code in {inst_path} ({inst_type} instance: {inst_name})'; "
                    f"unset CLAUDECODE; "
                    f"claude; while true; do $SHELL; done"
                )

                try:
                    result = subprocess.run(
                        [
                            "tmux", "new-window",
                            "-t", inner,
                            "-n", inst_name,
                            "-c", inst_path,
                            "-P", "-F", "#{window_id}",
                            reactivate_cmd,
                        ],
                        capture_output=True, text=True, check=True,
                    )
                    new_window_id = result.stdout.strip()
                    _create_bash_window(session, inst_name, inst_path)

                    try:
                        new_session_id = subprocess.run(
                            ["tmux", "display-message", "-t", inner, "-p", "#{session_id}"],
                            capture_output=True, text=True, check=True,
                        ).stdout.strip()
                        state.update_tmux_ids(inst_name, session, new_session_id, new_window_id)
                    except subprocess.CalledProcessError:
                        pass

                    console.print(f"  [green]\u2713[/green] Reactivated '{inst_name}'")
                except subprocess.CalledProcessError as e:
                    console.print(f"  [yellow]\u26a0[/yellow] Could not reactivate '{inst_name}': {e}")

            # Select the user's newly-created window so they land on it
            try:
                subprocess.run(
                    ["tmux", "select-window", "-t", f"{inner}:{name}"],
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
            os.execvp("tmux", ["tmux", "attach", "-t", f"={_outer_session_name(session)}"])


@app.command(name="list")
def instance_list() -> None:
    """List all instances and their tmux session status."""
    session = DEFAULT_SESSION
    instances = state.get_all_instances(session)

    if not instances:
        console.print("\n[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        return

    _display_session_table(session)


@app.command(name="rename")
def instance_rename(
    old: Optional[str] = None,
    new: Optional[str] = None,
) -> None:
    """Rename a ccmux instance.

    Args:
        old: Current instance name (or new name if only 1 arg given)
        new: New instance name
    """
    session = DEFAULT_SESSION

    if old is not None and new is not None:
        # Explicit: ccmux rename <old> <new>
        old_name = old
        new_name = sanitize_name(new)
        instance_data = state.get_instance(old_name, session)
        if not instance_data:
            console.print(f"[red]Error:[/red] Instance '{old_name}' not found.", style="bold")
            sys.exit(1)
    elif old is not None and new is None:
        # 1 arg: rename current instance to <new-name>
        new_name = sanitize_name(old)
        detected = detect_current_ccmux_instance_any()
        if not detected:
            console.print("[red]Error:[/red] Not in a ccmux instance.", style="bold")
            sys.exit(1)
        session = detected[0]
        old_name = detected[1]
        instance_data = detected[2]
    elif old is None and new is None:
        # Interactive mode
        instances = state.get_all_instances(session)
        if not instances:
            console.print(f"[yellow]No instances found.[/yellow]")
            return

        console.print(f"\n[bold]Instances:[/bold]")
        for i, inst in enumerate(instances):
            console.print(f"  {i + 1}. {inst.name}")

        choice = Prompt.ask(
            "\nSelect instance to rename",
            choices=[str(i + 1) for i in range(len(instances))],
        )
        old_name = instances[int(choice) - 1].name
        instance_data = state.get_instance(old_name, session)
        raw_new = Prompt.ask("New name")
        new_name = sanitize_name(raw_new)
    else:
        console.print("[red]Error:[/red] Provide both old and new names, one name to rename current instance, or run without args for interactive mode.", style="bold")
        sys.exit(1)

    if old_name == new_name:
        console.print(f"[yellow]Instance is already named '{old_name}'.[/yellow]")
        return

    # If it's a worktree, move the directory first (most likely to fail)
    is_wt = instance_data.is_worktree
    if is_wt:
        old_path = Path(instance_data.instance_path)
        repo_path = Path(instance_data.repo_path)
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
    if not state.rename_instance(old_name, new_name, session):
        if not state.get_instance(old_name, session):
            console.print(f"[red]Error:[/red] Instance '{old_name}' not found.", style="bold")
        else:
            console.print(f"[red]Error:[/red] Instance '{new_name}' already exists.", style="bold")
        sys.exit(1)

    # Update instance_path in state if worktree was moved
    if is_wt:
        state.update_instance(new_name, session, instance_path=str(new_path))

    # Rename tmux window if active (in inner session)
    tmux_window_id = instance_data.tmux_window_id
    if tmux_window_id and is_instance_window_active(session, tmux_window_id):
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


@app.command(name="attach")
def attach() -> None:
    """Attach to the ccmux tmux session."""
    session = DEFAULT_SESSION

    session_obj = state.get_session(session)
    if session_obj is None:
        console.print(f"[red]Error:[/red] No ccmux session found.", style="bold")
        console.print(f"\nCreate an instance with: [cyan]ccmux new[/cyan]")
        sys.exit(1)

    inner = _inner_session_name(session)
    if not tmux_session_exists(inner):
        console.print(f"[red]Error:[/red] Tmux session no longer exists.", style="bold")
        console.print(f"\nThe tmux session was closed. Activate instances with: [cyan]ccmux activate[/cyan]")
        sys.exit(1)

    _ensure_outer_session(session)
    _notify_sidebars(session)
    os.execvp("tmux", ["tmux", "attach", "-t", f"={_outer_session_name(session)}"])


@app.command(name="activate")
def instance_activate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Activate Claude Code in an instance (useful if tmux window was closed).

    If no name is provided, activates all inactive instances.

    Args:
        name: Instance name to activate (omit to activate all)
        yes: Skip confirmation prompt (default: False)
    """
    session = DEFAULT_SESSION
    if name is None:
        _activate_all_in_session(session, yes)
    else:
        _activate_single_instance(session, name, yes)


@app.command(name="deactivate")
def instance_deactivate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Deactivate Claude Code instance(s) by killing tmux window (keeps instance).

    If no name is provided, deactivates all active instances.

    Args:
        name: Instance name to deactivate (omit to deactivate all)
        yes: Skip confirmation prompt (default: False)
    """
    session = DEFAULT_SESSION

    instances = state.get_all_instances(session)

    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        sys.exit(0)

    # Check which instances are active (checks inner session)
    active_instances = []
    for inst in instances:
        if is_instance_window_active(session, inst.tmux_window_id):
            active_instances.append(inst)

    if name is None:
        if not active_instances:
            console.print(f"\n[yellow]No active instances to deactivate.[/yellow]")
            return

        console.print(f"\n[bold yellow]Deactivating {len(active_instances)} active instance(s):[/bold yellow]")
        for inst in active_instances:
            console.print(f"  \u2022 {inst.name}")
        console.print()

        if not yes:
            if not Confirm.ask(f"Deactivate all {len(active_instances)} instance(s)?", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        deactivated_count = 0
        for inst in active_instances:
            inst_name = inst.name
            tmux_window_id = inst.tmux_window_id
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
        if inst.name == name:
            instance = inst
            break

    if instance is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        sys.exit(1)

    if instance not in active_instances:
        console.print(f"[yellow]Instance '{name}' is already inactive.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating instance '{name}'[/bold yellow]")

    tmux_wid = instance.tmux_window_id
    if tmux_wid:
        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", tmux_wid],
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
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
    all_instances: Annotated[bool, Parameter(name=["--all"], negative="")] = False,
) -> None:
    """Remove instance(s) permanently (deactivates and deletes worktree).

    If no name is provided, auto-detects the current instance.
    Use --all to remove all instances.

    Args:
        name: Instance name to remove (auto-detects if omitted)
        yes: Skip confirmation prompt (default: False)
        all_instances: Remove all instances
    """
    session = DEFAULT_SESSION

    # Auto-detect instance when no name given and --all not set
    if name is None and not all_instances:
        detected = detect_current_ccmux_instance_any()
        if detected:
            session, name = detected[0], detected[1]
        else:
            console.print("[red]Error:[/red] No instance name provided and could not auto-detect.", style="bold")
            console.print("  Run from within a ccmux instance, or specify a name:")
            console.print("    [cyan]ccmux remove <name>[/cyan]")
            console.print("  To remove all instances:")
            console.print("    [cyan]ccmux remove --all[/cyan]")
            sys.exit(1)

    worktrees = state.get_all_instances(session)

    if not worktrees:
        console.print(f"[yellow]No instances found.[/yellow]")
        sys.exit(0)

    # Check which are active (checks inner session)
    active_worktrees = []
    inactive_worktrees = []
    for wt in worktrees:
        if is_instance_window_active(session, wt.tmux_window_id):
            active_worktrees.append(wt)
        else:
            inactive_worktrees.append(wt)

    if name is None:
        console.print(f"\n[bold red]WARNING: This will permanently delete {len(worktrees)} instance(s)[/bold red]")
        console.print("[red]Any uncommitted changes will be lost![/red]\n")

        if active_worktrees:
            console.print(f"  Active ({len(active_worktrees)}):")
            for wt in active_worktrees:
                console.print(f"    \u2022 {wt.name}")
        if inactive_worktrees:
            console.print(f"  Inactive ({len(inactive_worktrees)}):")
            for wt in inactive_worktrees:
                console.print(f"    \u2022 {wt.name}")
        console.print()

        if not yes:
            if not Confirm.ask(f"[bold red]Permanently remove all {len(worktrees)} instance(s)?[/bold red]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        removed_count = 0
        for wt in worktrees:
            wt_name = wt.name
            wt_path = Path(wt.instance_path)
            is_active = wt in active_worktrees
            is_main_repo = not wt.is_worktree

            if is_active:
                tmux_window_id = wt.tmux_window_id
                if tmux_window_id:
                    try:
                        subprocess.run(
                            ["tmux", "kill-window", "-t", tmux_window_id],
                            check=True, capture_output=True,
                        )
                        console.print(f"  [green]\u2713[/green] Deactivated '{wt_name}'")
                    except subprocess.CalledProcessError:
                        console.print(f"  [yellow]Window '{wt_name}' already closed[/yellow]")

                # Also kill the corresponding bash window
                bash = _bash_session_name(session)
                try:
                    subprocess.run(
                        ["tmux", "kill-window", "-t", f"{bash}:{wt_name}"],
                        check=True, capture_output=True,
                    )
                except subprocess.CalledProcessError:
                    pass

            prefix = "    " if is_active else "  "

            if is_main_repo:
                console.print(f"{prefix}[dim]Main repository - no git worktree to remove[/dim]")
            elif worktree_exists(wt_path, Path(wt.repo_path)):
                try:
                    repo_path = Path(wt.repo_path)
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

            state.remove_instance(wt_name, session)
            console.print(f"{prefix}[green]\u2713[/green] Removed '{wt_name}' from tracking")
            removed_count += 1

        # Kill all tmux sessions (outer, inner, bash)
        inner = _inner_session_name(session)
        bash = _bash_session_name(session)
        outer = _outer_session_name(session)
        if tmux_session_exists(outer):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", f"={outer}"],
                    check=True, capture_output=True,
                )
                console.print(f"\n[green]\u2713[/green] Killed outer tmux session '{outer}'")
            except subprocess.CalledProcessError:
                console.print(f"\n[yellow]\u26a0[/yellow] Could not kill outer tmux session '{outer}'")
        if tmux_session_exists(inner):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", f"={inner}"],
                    check=True, capture_output=True,
                )
                console.print(f"[green]\u2713[/green] Killed inner tmux session '{inner}'")
            except subprocess.CalledProcessError:
                console.print(f"[yellow]\u26a0[/yellow] Could not kill inner tmux session '{inner}'")
        if tmux_session_exists(bash):
            try:
                subprocess.run(
                    ["tmux", "kill-session", "-t", f"={bash}"],
                    check=True, capture_output=True,
                )
                console.print(f"[green]\u2713[/green] Killed bash tmux session '{bash}'")
            except subprocess.CalledProcessError:
                console.print(f"[yellow]\u26a0[/yellow] Could not kill bash tmux session '{bash}'")

        console.print(f"\n[bold green]Success![/bold green] Removed {removed_count} instance(s).")
        return

    # Remove single instance
    worktree = None
    for wt in worktrees:
        if wt.name == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list[/cyan]")
        sys.exit(1)

    wt_path = Path(worktree.instance_path)
    is_active = worktree in active_worktrees
    is_main_repo = not worktree.is_worktree

    if is_main_repo:
        console.print(f"\n[bold red]WARNING: Removing main repository '{name}' from tracking[/bold red]")
        console.print("[yellow]This will only remove it from ccmux tracking, not delete the repository itself.[/yellow]")
    else:
        console.print(f"\n[bold red]WARNING: Removing instance '{name}'[/bold red]")
        console.print("[red]This will permanently delete the worktree and any uncommitted changes![/red]")

    console.print(f"  Path: {wt_path}")
    console.print(f"  Status: {'Active' if is_active else 'Inactive'}\n")

    if not yes:
        prompt = f"[bold red]Remove '{name}' from tracking?[/bold red]" if is_main_repo else f"[bold red]Permanently remove instance '{name}'?[/bold red]"
        if not Confirm.ask(prompt, default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    if is_active:
        tmux_window_id = worktree.tmux_window_id
        if tmux_window_id:
            try:
                subprocess.run(
                    ["tmux", "kill-window", "-t", tmux_window_id],
                    check=True, capture_output=True,
                )
                console.print(f"  [green]\u2713[/green] Deactivated '{name}'")
            except subprocess.CalledProcessError:
                console.print(f"  [yellow]Window '{name}' already closed[/yellow]")

        # Also kill the corresponding bash window
        bash = _bash_session_name(session)
        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", f"{bash}:{name}"],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass

    if is_main_repo:
        console.print(f"  [dim]Main repository - no git worktree to remove[/dim]")
    elif worktree_exists(wt_path, Path(worktree.repo_path)):
        try:
            repo_path = Path(worktree.repo_path)
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

    state.remove_instance(name, session)
    _notify_sidebars(session)
    console.print(f"  [green]\u2713[/green] Removed '{name}' from tracking")

    # If no instances remain, clean up all tmux sessions
    remaining = state.get_all_instances(session)
    if not remaining:
        _uninstall_inner_hook(session)
        _kill_outer_session(session)
        inner = _inner_session_name(session)
        if tmux_session_exists(inner):
            subprocess.run(
                ["tmux", "kill-session", "-t", f"={inner}"],
                check=True, capture_output=True,
            )

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
    from ccmux.ui.tmux import get_tmux_config_content

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


@app.command(name="detach")
def detach(
    *,
    all_clients: Annotated[bool, Parameter(name=["-a", "--all"], negative="")] = False,
) -> None:
    """Detach the ccmux tmux session.

    By default, detaches only the most recently active client.
    Use --all / -a to detach all clients attached to the session.
    """
    session = DEFAULT_SESSION
    outer = _outer_session_name(session)
    if not tmux_session_exists(outer):
        console.print(f"[red]Error:[/red] No active ccmux session.", style="bold")
        sys.exit(1)
    try:
        if all_clients:
            subprocess.run(
                ["tmux", "detach-client", "-s", outer],
                check=True, capture_output=True,
            )
        else:
            subprocess.run(
                ["tmux", "detach-client", "-t", outer],
                check=True, capture_output=True,
            )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error detaching:[/red] {e}", style="bold")
        sys.exit(1)


def main():
    """Main entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
