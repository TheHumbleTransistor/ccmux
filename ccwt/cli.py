#!/usr/bin/env python3
"""Claude Code Worktrees CLI - Manage multiple Claude Code instances."""

import os
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cyclopts
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

console = Console()
app = cyclopts.App(
    name="ccwt",
    help="Claude Code Worktrees - Manage multiple Claude Code instances in git worktrees",
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
    session: str = "claude-cluster",
) -> None:
    """Create a new git worktree and launch Claude Code in a tmux window.

    Args:
        name: Name for the worktree/branch (generates random animal name if not provided)
        session: Tmux session name (default: claude-cluster)
    """
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

    # Generate or sanitize name
    if name is None:
        # Try to find an unused random name
        for _ in range(20):
            candidate = sanitize_name(generate_animal_name())
            worktree_path = repo_root / ".worktrees" / candidate
            if not worktree_exists(worktree_path):
                name = candidate
                break

        # If still no name, add numeric suffix
        if name is None:
            base = sanitize_name(generate_animal_name())
            suffix = random.randint(10, 99)
            name = f"{base}-{suffix}"
    else:
        name = sanitize_name(name)

    worktree_path = repo_root / ".worktrees" / name

    # Create .worktrees directory if needed
    (repo_root / ".worktrees").mkdir(exist_ok=True)

    # Create detached worktree based on default branch
    console.print(f"\n[bold cyan]Creating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Repo root: {repo_root}")
    console.print(f"  Worktree:  {worktree_path}")
    console.print(f"  Based on:  {default_branch} (detached)")

    try:
        if worktree_exists(worktree_path):
            console.print("  [yellow]Worktree already exists, reusing it.[/yellow]")
        else:
            # Create detached worktree based on default branch HEAD
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree_path), default_branch],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created detached worktree from {default_branch}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating worktree:[/red] {e}", style="bold")
        sys.exit(1)

    # Create or attach to tmux session
    if not tmux_session_exists(session):
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session, "-n", "home"],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created tmux session '{session}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
            sys.exit(1)

    # Create new tmux window and launch Claude
    try:
        launch_cmd = (
            f"echo 'Launching Claude Code in {worktree_path} (branch {name})'; "
            f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
        )

        subprocess.run(
            [
                "tmux", "new-window",
                "-t", f"{session}",
                "-n", name,
                "-c", str(worktree_path),
                launch_cmd,
            ],
            check=True,
        )

        subprocess.run(
            ["tmux", "select-window", "-t", f"{session}:{name}"],
            check=True,
        )

        console.print(f"  [green]✓[/green] Launched Claude Code in tmux window '{name}'")
        console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
        console.print(f"Attach with: [cyan]tmux attach -t {session}[/cyan]")

        # Auto-attach if not already in tmux
        if "TMUX" not in os.environ:
            console.print()
            if Confirm.ask("Attach to tmux session now?", default=True):
                os.execvp("tmux", ["tmux", "attach", "-t", session])

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error launching Claude Code:[/red] {e}", style="bold")
        sys.exit(1)


@app.command
def list(
    *,
    session: str = "claude-cluster",
) -> None:
    """List all worktrees and their tmux session status.

    Args:
        session: Tmux session name (default: claude-cluster)
    """
    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[red]Error:[/red] Not inside a git repository.", style="bold")
        sys.exit(1)

    worktrees = get_all_worktrees(repo_root)
    tmux_windows = get_tmux_windows(session)

    if not worktrees:
        console.print("\n[yellow]No worktrees found in .worktrees/[/yellow]")
        console.print(f"Create one with: [cyan]ccwt new[/cyan]")
        return

    # Create Rich table
    table = Table(title=f"Claude Code Worktrees (session: {session})", show_header=True)
    table.add_column("Worktree", style="cyan", no_wrap=True)
    table.add_column("Branch", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Path", style="dim")

    for wt in worktrees:
        name = wt["name"]
        branch = wt.get("branch", "unknown")
        path = wt["path"]

        # Check if there's an active tmux window
        if name in tmux_windows:
            status = "[green]● Active[/green]"
        else:
            status = "[dim]○ Inactive[/dim]"

        table.add_row(name, branch, status, path)

    console.print()
    console.print(table)
    console.print()

    # Show summary
    active_count = sum(1 for wt in worktrees if wt["name"] in tmux_windows)
    total_count = len(worktrees)
    console.print(f"Total: {total_count} worktrees, {active_count} active, {total_count - active_count} inactive")
    console.print()


@app.command
def destroy(
    name: Optional[str] = None,
    *,
    session: str = "claude-cluster",
    remove_worktree: bool = False,
    all: bool = False,
    no_confirm: bool = False,
) -> None:
    """Destroy Claude Code instance(s) (kill tmux window).

    Args:
        name: Session name to destroy (auto-detects if running inside tmux)
        session: Tmux session name (default: claude-cluster)
        remove_worktree: Also remove the git worktree (default: False)
        all: Destroy all active sessions (default: False)
        no_confirm: Skip confirmation prompt (default: False)
    """
    # Handle --all flag
    if all:
        repo_root = get_repo_root()
        if repo_root is None:
            console.print("[red]Error:[/red] Not inside a git repository.", style="bold")
            sys.exit(1)

        worktrees = get_all_worktrees(repo_root)
        tmux_windows = get_tmux_windows(session)

        # Separate active and inactive worktrees
        active_worktrees = [wt for wt in worktrees if wt["name"] in tmux_windows]
        inactive_worktrees = [wt for wt in worktrees if wt["name"] not in tmux_windows]

        # Decide which worktrees to process based on flags
        if remove_worktree:
            # When removing worktrees, process both active and inactive
            worktrees_to_process = worktrees
            if not worktrees_to_process:
                console.print("\n[yellow]No worktrees to destroy.[/yellow]")
                return

            console.print(f"\n[bold yellow]Found {len(worktrees_to_process)} worktree(s):[/bold yellow]")
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
                if not Confirm.ask(f"Destroy and remove all {len(worktrees_to_process)} worktree(s)?", default=False):
                    console.print("[yellow]Cancelled.[/yellow]")
                    return
        else:
            # Without --remove-worktree, only process active sessions
            worktrees_to_process = active_worktrees
            if not worktrees_to_process:
                console.print("\n[yellow]No active sessions to destroy.[/yellow]")
                return

            console.print(f"\n[bold yellow]Found {len(worktrees_to_process)} active session(s):[/bold yellow]")
            for wt in worktrees_to_process:
                console.print(f"  • {wt['name']}")
            console.print()

            if not no_confirm:
                if not Confirm.ask(f"Destroy all {len(worktrees_to_process)} session(s)?", default=False):
                    console.print("[yellow]Cancelled.[/yellow]")
                    return

        # Process worktrees
        destroyed_count = 0
        removed_count = 0
        for wt in worktrees_to_process:
            wt_name = wt["name"]
            is_active = wt_name in tmux_windows

            # Kill tmux window if active
            if is_active:
                try:
                    subprocess.run(
                        ["tmux", "kill-window", "-t", f"{session}:{wt_name}"],
                        check=True,
                        capture_output=True,
                    )
                    console.print(f"  [green]✓[/green] Killed tmux window '{wt_name}'")
                    destroyed_count += 1
                except subprocess.CalledProcessError:
                    console.print(f"  [yellow]Window '{wt_name}' not found or already closed[/yellow]")

            # Remove worktree if requested
            if remove_worktree:
                worktree_path = Path(wt["path"])
                if worktree_exists(worktree_path):
                    try:
                        subprocess.run(
                            ["git", "worktree", "remove", "--force", str(worktree_path)],
                            check=True,
                        )
                        prefix = "    " if is_active else "  "
                        console.print(f"{prefix}[green]✓[/green] Removed worktree '{wt_name}'")
                        removed_count += 1
                    except subprocess.CalledProcessError as e:
                        prefix = "    " if is_active else "  "
                        console.print(f"{prefix}[red]Error removing worktree:[/red] {e}")

        # Summary message
        summary_parts = []
        if destroyed_count > 0:
            summary_parts.append(f"{destroyed_count} session(s)")
        if removed_count > 0:
            summary_parts.append(f"{removed_count} worktree(s)")

        if summary_parts:
            console.print(f"\n[bold green]Success![/bold green] Destroyed {' and removed '.join(summary_parts)}.")
        else:
            console.print(f"\n[yellow]Nothing was destroyed.[/yellow]")
        return

    # Auto-detect name from tmux if not provided
    if name is None:
        current_window = get_current_tmux_window()
        current_session = get_current_tmux_session()

        if current_window and current_session == session:
            name = current_window
            console.print(f"[cyan]Auto-detected window:[/cyan] {name}")
        else:
            console.print("[red]Error:[/red] Not running inside a tmux window, please specify name.", style="bold")
            sys.exit(1)

    # Kill the tmux window
    console.print(f"\n[bold yellow]Destroying Claude Code instance:[/bold yellow] {name}")

    try:
        subprocess.run(
            ["tmux", "kill-window", "-t", f"{session}:{name}"],
            check=True,
            capture_output=True,
        )
        console.print(f"  [green]✓[/green] Killed tmux window '{name}'")
    except subprocess.CalledProcessError:
        console.print(f"  [yellow]Window '{name}' not found or already closed[/yellow]")

    # Optionally remove worktree
    if remove_worktree:
        repo_root = get_repo_root()
        if repo_root:
            worktree_path = repo_root / ".worktrees" / name

            if worktree_exists(worktree_path):
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        check=True,
                    )
                    console.print(f"  [green]✓[/green] Removed worktree at {worktree_path}")
                except subprocess.CalledProcessError as e:
                    console.print(f"  [red]Error removing worktree:[/red] {e}")
            else:
                console.print(f"  [yellow]Worktree not found:[/yellow] {worktree_path}")

    console.print(f"\n[bold green]Success![/bold green] Instance '{name}' destroyed.")


@app.command
def reopen(
    name: Optional[str] = None,
    *,
    session: str = "claude-cluster",
    all: bool = False,
    no_confirm: bool = False,
) -> None:
    """Reopen a worktree in tmux (useful if tmux window was closed).

    Args:
        name: Worktree name to reopen
        session: Tmux session name (default: claude-cluster)
        all: Reopen all inactive worktrees (default: False)
        no_confirm: Skip confirmation prompt (default: False)
    """
    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[red]Error:[/red] Not inside a git repository.", style="bold")
        sys.exit(1)

    worktrees = get_all_worktrees(repo_root)
    tmux_windows = get_tmux_windows(session)

    if all:
        # Reopen all inactive worktrees
        inactive_worktrees = [wt for wt in worktrees if wt["name"] not in tmux_windows]

        if not inactive_worktrees:
            console.print("\n[yellow]No inactive worktrees to reopen.[/yellow]")
            return

        console.print(f"\n[bold cyan]Found {len(inactive_worktrees)} inactive worktree(s):[/bold cyan]")
        for wt in inactive_worktrees:
            console.print(f"  • {wt['name']}")
        console.print()

        if not no_confirm:
            if not Confirm.ask(f"Reopen all {len(inactive_worktrees)} worktree(s)?", default=True):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        reopened_count = 0
        for wt in inactive_worktrees:
            wt_name = wt["name"]
            wt_path = wt["path"]

            # Create or attach to tmux session
            if not tmux_session_exists(session):
                try:
                    subprocess.run(
                        ["tmux", "new-session", "-d", "-s", session, "-n", "home"],
                        check=True,
                    )
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
                    continue

            # Create new tmux window
            try:
                launch_cmd = (
                    f"echo 'Reopening Claude Code in {wt_path} (branch {wt_name})'; "
                    f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
                )

                subprocess.run(
                    [
                        "tmux", "new-window",
                        "-t", f"{session}",
                        "-n", wt_name,
                        "-c", wt_path,
                        launch_cmd,
                    ],
                    check=True,
                    capture_output=True,
                )
                console.print(f"  [green]✓[/green] Reopened '{wt_name}'")
                reopened_count += 1
            except subprocess.CalledProcessError as e:
                console.print(f"  [red]Error reopening '{wt_name}':[/red] {e}")

        console.print(f"\n[bold green]Success![/bold green] Reopened {reopened_count} worktree(s).")
        return

    # Reopen single worktree
    if name is None:
        console.print("[red]Error:[/red] Please specify a worktree name or use --all.", style="bold")
        sys.exit(1)

    # Find the worktree
    worktree = None
    for wt in worktrees:
        if wt["name"] == name:
            worktree = wt
            break

    if worktree is None:
        console.print(f"[red]Error:[/red] Worktree '{name}' not found.", style="bold")
        console.print(f"List worktrees with: [cyan]ccwt list[/cyan]")
        sys.exit(1)

    # Check if already active
    if name in tmux_windows:
        console.print(f"[yellow]Worktree '{name}' already has an active tmux window.[/yellow]")
        return

    wt_path = worktree["path"]

    console.print(f"\n[bold cyan]Reopening Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Worktree: {wt_path}")

    # Create or attach to tmux session
    if not tmux_session_exists(session):
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session, "-n", "home"],
                check=True,
            )
            console.print(f"  [green]✓[/green] Created tmux session '{session}'")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating tmux session:[/red] {e}", style="bold")
            sys.exit(1)

    # Create new tmux window
    try:
        launch_cmd = (
            f"echo 'Reopening Claude Code in {wt_path} (branch {name})'; "
            f"claude || {{ echo 'Claude Code failed to start. Press enter to close.'; read; }}"
        )

        subprocess.run(
            [
                "tmux", "new-window",
                "-t", f"{session}",
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

        console.print(f"  [green]✓[/green] Reopened Claude Code in tmux window '{name}'")
        console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
        console.print(f"Attach with: [cyan]tmux attach -t {session}[/cyan]")

        # Auto-attach if not already in tmux
        if "TMUX" not in os.environ:
            console.print()
            if no_confirm or Confirm.ask("Attach to tmux session now?", default=True):
                os.execvp("tmux", ["tmux", "attach", "-t", session])

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error reopening Claude Code:[/red] {e}", style="bold")
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
