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

    # Generate or sanitize name
    if name is None:
        # Try to find an unused random name
        for _ in range(20):
            candidate = sanitize_name(generate_animal_name())
            worktree_path = repo_root / ".worktrees" / candidate
            if not worktree_exists(worktree_path) and not branch_exists(candidate):
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

    # Create worktree and branch
    console.print(f"\n[bold cyan]Creating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Repo root: {repo_root}")
    console.print(f"  Worktree:  {worktree_path}")
    console.print(f"  Branch:    {name}")

    try:
        if worktree_exists(worktree_path):
            console.print("  [yellow]Worktree already exists, reusing it.[/yellow]")
        elif branch_exists(name):
            # Branch exists, attach worktree to it
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), name],
                check=True,
            )
            console.print("  [green][/green] Attached to existing branch")
        else:
            # Create new branch and worktree
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", name],
                check=True,
            )
            console.print("  [green][/green] Created new branch and worktree")
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
            console.print(f"  [green][/green] Created tmux session '{session}'")
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

        console.print(f"  [green][/green] Launched Claude Code in tmux window '{name}'")
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
def destroy(
    name: Optional[str] = None,
    *,
    session: str = "claude-cluster",
    remove_worktree: bool = False,
) -> None:
    """Destroy a Claude Code instance (kill tmux window).

    Args:
        name: Session name to destroy (auto-detects if running inside tmux)
        session: Tmux session name (default: claude-cluster)
        remove_worktree: Also remove the git worktree (default: False)
    """
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
        console.print(f"  [green][/green] Killed tmux window '{name}'")
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
                        ["git", "worktree", "remove", str(worktree_path)],
                        check=True,
                    )
                    console.print(f"  [green][/green] Removed worktree at {worktree_path}")
                except subprocess.CalledProcessError as e:
                    console.print(f"  [red]Error removing worktree:[/red] {e}")
            else:
                console.print(f"  [yellow]Worktree not found:[/yellow] {worktree_path}")

    console.print(f"\n[bold green]Success![/bold green] Instance '{name}' destroyed.")


def main():
    """Main entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
