#!/usr/bin/env python3
"""Claude Code Multiplexer CLI - Manage multiple Claude Code instances."""

import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from cyclopts import Parameter
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ccmux import state

# Default session name
DEFAULT_SESSION = "ccmux"


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
    help="Claude Code Multiplexer - Manage multiple Claude Code instances",
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


# --- Commands ---

@app.command
def new(
    name: Optional[str] = None,
    *,
    worktree: Annotated[bool, Parameter(names=["-w", "--worktree"])] = False,
    common: CommonConfig,
) -> None:
    """Create a new Claude Code instance in main repo or as a git worktree.

    Args:
        name: Name for the instance (generates random animal name if not provided)
        worktree: Create instance as a git worktree instead of using main repo
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
        # Check if main repo is already in use
        existing_main = state.find_main_repo_instance(str(repo_root), session)
        if existing_main:
            console.print(f"[yellow]Warning:[/yellow] Main repository already has an instance: '{existing_main['name']}'")
            if Confirm.ask("Create a worktree instead?", default=True):
                create_as_worktree = True
            else:
                console.print("[red]Aborted:[/red] Main repository already in use.")
                sys.exit(1)

    # Generate or sanitize name
    if name is None:
        # Try to find an unused random name
        for _ in range(20):
            candidate = sanitize_name(generate_animal_name())
            if create_as_worktree:
                test_path = repo_root / ".worktrees" / candidate
                if not worktree_exists(test_path):
                    name = candidate
                    break
            else:
                # For main repo, just check if the name is unused in state
                if not state.get_worktree(session, candidate):
                    name = candidate
                    break

        # If still no name, add numeric suffix
        if name is None:
            base = sanitize_name(generate_animal_name())
            suffix = random.randint(10, 99)
            name = f"{base}-{suffix}"
    else:
        name = sanitize_name(name)

    # Set instance path based on type
    if create_as_worktree:
        instance_path = repo_root / ".worktrees" / name
        # Create .worktrees directory if needed
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
                # Create detached worktree based on default branch HEAD
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(instance_path), default_branch],
                    check=True,
                )
                console.print(f"  [green]✓[/green] Created detached worktree from {default_branch}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating worktree:[/red] {e}", style="bold")
            sys.exit(1)

    # Check if this is the first instance in the ccmux session
    session_data = state.get_session(session)
    is_first_instance = session_data is None

    # Create or attach to tmux session
    instance_type = "worktree" if create_as_worktree else "main repo"
    launch_cmd = (
        f"echo 'Launching Claude Code in {instance_path} ({instance_type} instance: {name})'; "
        f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
    )

    if is_first_instance:
        # First instance: create session with this window as the only window
        try:
            subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", session,
                    "-n", name,
                    "-c", str(instance_path),
                    launch_cmd,
                ],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created tmux session '{session}' with window '{name}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
            sys.exit(1)
    else:
        # Not the first instance: add a new window to existing session
        try:
            subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", f"{session}",
                    "-n", name,
                    "-c", str(instance_path),
                    launch_cmd,
                ],
                check=True,
            )

            subprocess.run(
                ["tmux", "select-window", "-t", f"{session}:{name}"],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created new window '{name}' in session '{session}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux window:[/red] {e}", style="bold")
            sys.exit(1)

    # Get tmux IDs and save to state
    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        tmux_window_id = subprocess.run(
            ["tmux", "display-message", "-t", f"{session}:{name}", "-p", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Save instance to state
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
        # If we can't get IDs, still save to state without them
        state.add_worktree(
            session_name=session,
            worktree_name=name,
            repo_path=str(repo_root),
            worktree_path=str(instance_path),
            is_worktree=create_as_worktree
        )

    console.print(f"  [green]✓[/green] Launched Claude Code in tmux window '{name}'")
    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")

    # Auto-attach if not already in tmux
    if "TMUX" not in os.environ:
        console.print()
        if Confirm.ask("Attach to tmux session now?", default=True):
            os.execvp("tmux", ["tmux", "attach", "-t", session])


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
    table.add_column("Branch", style="magenta")
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
                branch = "(detached)"
        except subprocess.CalledProcessError:
            pass

        # Get tmux window name and check if active
        tmux_window_name = ""
        status = "[dim]○ Inactive[/dim]"
        if tmux_window_id:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                tmux_window_name = result.stdout.strip()
                # Only mark as active if we got a window name
                if tmux_window_name:
                    status = "[green]● Active[/green]"
                    active_count += 1
            except subprocess.CalledProcessError:
                # Window doesn't exist anymore
                pass

        table.add_row(repo_name, name, instance_type, branch, status, tmux_window_name, str(instance_path))

    console.print()
    console.print(table)
    console.print()

    # Show summary
    total_count = len(instances)
    console.print(f"Total: {total_count} instances, {active_count} active, {total_count - active_count} inactive")
    console.print()


@app.command
def list(
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
        # Display tables for all sessions
        all_state = state.load_state()
        sessions = all_state.get("sessions", {})

        if not sessions:
            console.print("\n[yellow]No sessions found.[/yellow]")
            console.print(f"Create one with: [cyan]ccmux new[/cyan]")
            return

        for session_name in sessions.keys():
            _display_session_table(session_name)
    else:
        # Display table for single session
        session = common.session
        instances = state.get_all_worktrees(session)

        if not instances:
            console.print("\n[yellow]No instances found.[/yellow]")
            console.print(f"Create one with: [cyan]ccmux new[/cyan]")
            return

        _display_session_table(session)


@app.command
def deactivate(
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

    # Get instances from state
    instances = state.get_all_worktrees(session)

    if not instances:
        console.print(f"[yellow]No instances found in session '{session}'.[/yellow]")
        sys.exit(0)

    # Check which instances are active
    active_instances = []
    for inst in instances:
        tmux_window_id = inst.get("tmux_window_id")
        if tmux_window_id:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.stdout.strip():
                    active_instances.append(inst)
            except subprocess.CalledProcessError:
                pass

    if name is None:
        # Deactivate all active instances
        if not active_instances:
            console.print(f"\n[yellow]No active instances to deactivate in session '{session}'.[/yellow]")
            return

        console.print(f"\n[bold yellow]Deactivating {len(active_instances)} active instance(s) in session '{session}':[/bold yellow]")
        for inst in active_instances:
            console.print(f"  • {inst['name']}")
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
                        check=True,
                        capture_output=True,
                    )
                    console.print(f"  [green]✓[/green] Deactivated '{inst_name}'")
                    deactivated_count += 1
                except subprocess.CalledProcessError:
                    console.print(f"  [yellow]Window '{inst_name}' not found or already closed[/yellow]")

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

    # Check if it's active
    if instance not in active_instances:
        console.print(f"[yellow]Instance '{name}' is already inactive.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating instance '{name}' in session '{session}'[/bold yellow]")

    tmux_window_id = instance.get("tmux_window_id")
    if tmux_window_id:
        try:
            subprocess.run(
                ["tmux", "kill-window", "-t", tmux_window_id],
                check=True,
                capture_output=True,
            )
            console.print(f"  [green]✓[/green] Deactivated '{name}'")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]Window '{name}' not found or already closed[/yellow]")

    console.print(f"\n[bold green]Success![/bold green] Instance '{name}' deactivated.")


@app.command
def remove(
    name: Optional[str] = None,
    *,
    common: CommonConfig,
    no_confirm: bool = False,
) -> None:
    """Remove worktree(s) permanently (deactivates session and deletes worktree).

    If no name is provided, removes all worktrees in the session.
    ⚠️  WARNING: This permanently deletes worktrees and any uncommitted changes!

    Args:
        name: Worktree name to remove (omit to remove all)
        common: Common parameters (session, etc.)
        no_confirm: Skip confirmation prompt (default: False)
    """
    session = common.session

    # Get worktrees from state
    worktrees = state.get_all_worktrees(session)

    if not worktrees:
        console.print(f"[yellow]No worktrees found in session '{session}'.[/yellow]")
        sys.exit(0)

    # Check which worktrees are active
    active_worktrees = []
    inactive_worktrees = []
    for wt in worktrees:
        tmux_window_id = wt.get("tmux_window_id")
        is_active = False
        if tmux_window_id:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.stdout.strip():
                    is_active = True
            except subprocess.CalledProcessError:
                pass

        if is_active:
            active_worktrees.append(wt)
        else:
            inactive_worktrees.append(wt)

    if name is None:
        # Remove all worktrees
        console.print(f"\n[bold red]⚠️  WARNING: This will permanently delete {len(worktrees)} worktree(s) in session '{session}'[/bold red]")
        console.print("[red]Any uncommitted changes will be lost![/red]\n")

        if active_worktrees:
            console.print(f"  Active ({len(active_worktrees)}):")
            for wt in active_worktrees:
                console.print(f"    • {wt['name']}")
        if inactive_worktrees:
            console.print(f"  Inactive ({len(inactive_worktrees)}):")
            for wt in inactive_worktrees:
                console.print(f"    • {wt['name']}")
        console.print()

        if not no_confirm:
            if not Confirm.ask(f"[bold red]Permanently remove all {len(worktrees)} worktree(s)?[/bold red]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        removed_count = 0
        for wt in worktrees:
            wt_name = wt["name"]
            wt_path = Path(wt["worktree_path"])
            is_active = wt in active_worktrees

            # Deactivate if active
            if is_active:
                tmux_window_id = wt.get("tmux_window_id")
                if tmux_window_id:
                    try:
                        subprocess.run(
                            ["tmux", "kill-window", "-t", tmux_window_id],
                            check=True,
                            capture_output=True,
                        )
                        console.print(f"  [green]✓[/green] Deactivated '{wt_name}'")
                    except subprocess.CalledProcessError:
                        console.print(f"  [yellow]Window '{wt_name}' already closed[/yellow]")

            # Remove worktree
            if worktree_exists(wt_path):
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt_path)],
                        check=True,
                    )
                    # Remove from state
                    state.remove_worktree(session, wt_name)
                    prefix = "    " if is_active else "  "
                    console.print(f"{prefix}[green]✓[/green] Removed worktree '{wt_name}'")
                    removed_count += 1
                except subprocess.CalledProcessError as e:
                    prefix = "    " if is_active else "  "
                    console.print(f"{prefix}[red]Error removing worktree:[/red] {e}")

        console.print(f"\n[bold green]Success![/bold green] Removed {removed_count} worktree(s).")
        return

    # Remove single worktree
    worktree = None
    for wt in worktrees:
        if wt["name"] == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Worktree '{name}' not found in session '{session}'.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list --session {session}[/cyan]")
        sys.exit(1)

    wt_path = Path(worktree["worktree_path"])
    is_active = worktree in active_worktrees

    console.print(f"\n[bold red]⚠️  WARNING: Removing worktree '{name}' from session '{session}'[/bold red]")
    console.print("[red]This will permanently delete the worktree and any uncommitted changes![/red]")
    console.print(f"  Path: {wt_path}")
    console.print(f"  Status: {'Active' if is_active else 'Inactive'}\n")

    if not no_confirm:
        if not Confirm.ask(f"[bold red]Permanently remove worktree '{name}'?[/bold red]", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Deactivate if active
    if is_active:
        tmux_window_id = worktree.get("tmux_window_id")
        if tmux_window_id:
            try:
                subprocess.run(
                    ["tmux", "kill-window", "-t", tmux_window_id],
                    check=True,
                    capture_output=True,
                )
                console.print(f"  [green]✓[/green] Deactivated '{name}'")
            except subprocess.CalledProcessError:
                console.print(f"  [yellow]Window '{name}' already closed[/yellow]")

    # Remove worktree
    if worktree_exists(wt_path):
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                check=True,
            )
            # Remove from state
            state.remove_worktree(session, name)
            console.print(f"  [green]✓[/green] Removed worktree at {wt_path}")
        except subprocess.CalledProcessError as e:
            console.print(f"  [red]Error removing worktree:[/red] {e}")
            sys.exit(1)
    else:
        console.print(f"  [yellow]Worktree not found:[/yellow] {wt_path}")

    console.print(f"\n[bold green]Success![/bold green] Worktree '{name}' removed.")


@app.command
def which() -> None:
    """Show which worktree the current tmux window is associated with.

    Run this from within a tmux window to see which ccmux instance you're in.
    """
    # Check if we're in tmux
    if "TMUX" not in os.environ:
        console.print("[red]Error:[/red] Not running inside a tmux window.", style="bold")
        sys.exit(1)

    # Get current tmux IDs
    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        tmux_window_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error getting tmux IDs:[/red] {e}", style="bold")
        sys.exit(1)

    # Find worktree by tmux IDs
    result = state.find_worktree_by_tmux_ids(tmux_session_id, tmux_window_id)

    if result is None:
        console.print("[yellow]This tmux window is not associated with any ccmux instance.[/yellow]")
        sys.exit(0)

    session_name, worktree_name, worktree_data = result

    # Get repository name
    repo_path = Path(worktree_data["repo_path"])
    repo_name = repo_path.name

    # Get current branch
    worktree_path = Path(worktree_data["worktree_path"])
    try:
        branch_result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = branch_result.stdout.strip()
        if branch == "HEAD":
            branch = "(detached)"
    except subprocess.CalledProcessError:
        branch = "unknown"

    # Display info
    console.print(f"\n[bold cyan]Worktree:[/bold cyan] {worktree_name}")
    console.print(f"[bold cyan]Session:[/bold cyan]  {session_name}")
    console.print(f"[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[bold cyan]Branch:[/bold cyan] {branch}")
    console.print(f"[bold cyan]Path:[/bold cyan] {worktree_path}\n")


@app.command
def attach(
    *,
    common: CommonConfig,
) -> None:
    """Attach to a tmux session.

    Args:
        common: Common parameters (session, etc.)
    """
    session = common.session

    # Get session from state
    session_data = state.get_session(session)

    if session_data is None:
        console.print(f"[red]Error:[/red] ccmux session '{session}' not found.", style="bold")
        console.print(f"\nCreate an instance with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(1)

    # Get tmux session ID from state
    tmux_session_id = session_data.get("tmux_session_id")

    if tmux_session_id is None:
        console.print(f"[red]Error:[/red] No tmux session associated with ccmux session '{session}'.", style="bold")
        console.print(f"\nCreate an instance with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(1)

    # Check if tmux session still exists
    try:
        subprocess.run(
            ["tmux", "has-session", "-t", tmux_session_id],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        console.print(f"[red]Error:[/red] Tmux session no longer exists.", style="bold")
        console.print(f"\nThe tmux session was closed. Activate instances with: [cyan]ccmux activate --session {session}[/cyan]")
        sys.exit(1)

    # Use execvp to replace the current process with tmux attach
    os.execvp("tmux", ["tmux", "attach", "-t", tmux_session_id])


@app.command
def activate(
    name: Optional[str] = None,
    *,
    common: CommonConfig,
    no_confirm: bool = False,
) -> None:
    """Activate Claude Code in a worktree (useful if tmux window was closed).

    If no name is provided, activates all inactive worktrees in the session.

    Args:
        name: Worktree name to activate (omit to activate all)
        common: Common parameters (session, etc.)
        no_confirm: Skip confirmation prompt (default: False)
    """
    session = common.session

    # Get worktrees from state
    worktrees = state.get_all_worktrees(session)

    if not worktrees:
        console.print(f"[yellow]No worktrees found in session '{session}'.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new --session {session}[/cyan]")
        sys.exit(0)

    # Check which worktrees are inactive (tmux window doesn't exist)
    inactive_worktrees = []
    for wt in worktrees:
        tmux_window_id = wt.get("tmux_window_id")
        is_active = False

        if tmux_window_id:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.stdout.strip():
                    is_active = True
            except subprocess.CalledProcessError:
                pass

        if not is_active:
            inactive_worktrees.append(wt)

    if name is None:
        # Activate all inactive worktrees
        if not inactive_worktrees:
            console.print("\n[yellow]No inactive worktrees to activate.[/yellow]")
            return

        console.print(f"\n[bold cyan]Found {len(inactive_worktrees)} inactive worktree(s):[/bold cyan]")
        for wt in inactive_worktrees:
            console.print(f"  • {wt['name']}")
        console.print()

        if not no_confirm:
            if not Confirm.ask(f"Activate all {len(inactive_worktrees)} worktree(s)?", default=True):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        # Get session data and tmux session ID
        session_data = state.get_session(session)
        tmux_session_id = session_data.get("tmux_session_id") if session_data else None

        # Check if tmux session exists
        tmux_session_exists_flag = False
        if tmux_session_id:
            try:
                subprocess.run(
                    ["tmux", "has-session", "-t", tmux_session_id],
                    check=True,
                    capture_output=True,
                )
                tmux_session_exists_flag = True
            except subprocess.CalledProcessError:
                pass

        activated_count = 0
        for i, wt in enumerate(inactive_worktrees):
            wt_name = wt["name"]
            wt_path = wt["worktree_path"]

            launch_cmd = (
                f"echo 'Activating Claude Code in {wt_path}'; "
                f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
            )

            try:
                # If tmux session doesn't exist and this is the first worktree, create session with it
                if not tmux_session_exists_flag and i == 0:
                    subprocess.run(
                        [
                            "tmux", "new-session",
                            "-d",
                            "-s", session,
                            "-n", wt_name,
                            "-c", wt_path,
                            launch_cmd,
                        ],
                        check=True,
                        capture_output=True,
                    )
                    tmux_session_exists_flag = True
                    console.print(f"  [green]✓[/green] Created tmux session and activated '{wt_name}'")
                else:
                    # Create new window in existing session
                    subprocess.run(
                        [
                            "tmux", "new-window",
                            "-t", session,
                            "-n", wt_name,
                            "-c", wt_path,
                            launch_cmd,
                        ],
                        check=True,
                        capture_output=True,
                    )
                    console.print(f"  [green]✓[/green] Activated '{wt_name}'")

                # Update tmux IDs in state
                try:
                    new_tmux_session_id = subprocess.run(
                        ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()

                    new_tmux_window_id = subprocess.run(
                        ["tmux", "display-message", "-t", f"{session}:{wt_name}", "-p", "#{window_id}"],
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()

                    state.update_tmux_ids(session, wt_name, new_tmux_session_id, new_tmux_window_id)
                except subprocess.CalledProcessError:
                    pass

                activated_count += 1
            except subprocess.CalledProcessError as e:
                console.print(f"  [red]Error activating '{wt_name}':[/red] {e}")

        console.print(f"\n[bold green]Success![/bold green] Activated {activated_count} worktree(s).")
        return

    # Activate single worktree (name is provided)
    # Find the worktree in state
    worktree = None
    for wt in worktrees:
        if wt["name"] == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Worktree '{name}' not found in session '{session}'.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list --session {session}[/cyan]")
        sys.exit(1)

    # Check if already active
    is_active = worktree in [wt for wt in worktrees if wt not in inactive_worktrees]
    if is_active:
        console.print(f"[yellow]Worktree '{name}' already has an active tmux window.[/yellow]")
        return

    wt_path = worktree["worktree_path"]

    console.print(f"\n[bold cyan]Activating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Worktree: {wt_path}")

    # Get session data and tmux session ID
    session_data = state.get_session(session)
    tmux_session_id = session_data.get("tmux_session_id") if session_data else None

    # Check if tmux session exists
    tmux_session_exists_flag = False
    if tmux_session_id:
        try:
            subprocess.run(
                ["tmux", "has-session", "-t", tmux_session_id],
                check=True,
                capture_output=True,
            )
            tmux_session_exists_flag = True
        except subprocess.CalledProcessError:
            pass

    launch_cmd = (
        f"echo 'Activating Claude Code in {wt_path}'; "
        f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
    )

    try:
        # If tmux session doesn't exist, create it with this worktree
        if not tmux_session_exists_flag:
            subprocess.run(
                [
                    "tmux", "new-session",
                    "-d",
                    "-s", session,
                    "-n", name,
                    "-c", wt_path,
                    launch_cmd,
                ],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created tmux session and activated '{name}'")
        else:
            # Create new window in existing session
            subprocess.run(
                [
                    "tmux", "new-window",
                    "-t", session,
                    "-n", name,
                    "-c", wt_path,
                    launch_cmd,
                ],
                check=True,
            )

            subprocess.run(
                ["tmux", "select-window", "-t", f"{session}:{name}"],
                check=True,
            )
            console.print(f"  [green]✓[/green] Activated '{name}'")

        # Update tmux IDs in state
        try:
            tmux_session_id = subprocess.run(
                ["tmux", "display-message", "-t", f"{session}", "-p", "#{session_id}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            tmux_window_id = subprocess.run(
                ["tmux", "display-message", "-t", f"{session}:{name}", "-p", "#{window_id}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            state.update_tmux_ids(session, name, tmux_session_id, tmux_window_id)
        except subprocess.CalledProcessError:
            pass  # Continue even if we can't update IDs

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
    command, bound, _ = app.parse_args(tokens)
    return command(*bound.args, **bound.kwargs, common=common)


def main():
    """Main entry point for the CLI."""
    try:
        app.meta()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
