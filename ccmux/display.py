"""Rich table and info display for ccmux."""

import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ccmux import state
from ccmux.backend import get_backend
from ccmux.git_ops import get_branch_name
from ccmux.naming import is_session_window_active

console = Console()


def display_session_table() -> None:
    """Display a table of sessions."""
    sessions = state.get_all_sessions()

    if not sessions:
        console.print(f"\n[yellow]No sessions found.[/yellow]")
        return

    # Show Backend column only when sessions use more than one backend
    backend_names = {sess.backend_name for sess in sessions}
    show_backend_col = len(backend_names) > 1

    table = Table(title="Coding Sessions", show_header=True)
    table.add_column("Repository", style="yellow")
    table.add_column("Session", style="cyan", no_wrap=True)
    if show_backend_col:
        table.add_column("Backend", style="magenta")
    table.add_column("Type", style="green")
    table.add_column("Branch")
    table.add_column("Status", style="bold")
    table.add_column("Window", style="blue")
    table.add_column("Path", style="dim")

    active_count = 0
    for sess in sessions:
        row = _build_session_row(sess)
        if row["is_active"]:
            active_count += 1
        cols = [
            row["repo_name"],
            sess.name,
        ]
        if show_backend_col:
            backend = get_backend(sess.backend_name)
            cols.append(backend.display_name)
        cols += [
            row["session_type"],
            row["branch"],
            row["status"],
            row["tmux_window_name"],
            str(sess.session_path),
        ]
        table.add_row(*cols)

    console.print()
    console.print(table)
    console.print()

    total_count = len(sessions)
    console.print(
        f"Total: {total_count} sessions, {active_count} active, {total_count - active_count} inactive"
    )
    console.print()


def _build_session_row(sess) -> dict:
    """Build display data for one session row."""
    repo_name = Path(sess.repo_path).name
    session_type = "worktree" if sess.is_worktree else "root"

    branch_raw = get_branch_name(sess.session_path)
    if branch_raw == "HEAD":
        branch = "[dim](detached)[/dim]"
    elif branch_raw == "(unknown)":
        branch = branch_raw
    else:
        branch = f"[magenta]{branch_raw}[/magenta]"

    tmux_window_name = ""
    status = "[dim]\u25cb Inactive[/dim]"
    is_active = is_session_window_active(sess.tmux_cc_window_id)

    if is_active:
        tmux_window_name = _get_window_display_name(sess.tmux_cc_window_id)
        status = "[green]\u25cf Active[/green]"

    return {
        "repo_name": repo_name,
        "session_type": session_type,
        "branch": branch,
        "status": status,
        "tmux_window_name": tmux_window_name,
        "is_active": is_active,
    }


def _get_window_display_name(tmux_window_id: Optional[str]) -> str:
    """Get the display name of a tmux window by ID."""
    if not tmux_window_id:
        return ""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", tmux_window_id, "-p", "#{window_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def show_session_info(session_name: str, session_data) -> None:
    """Display info about a specific session."""
    repo_name = Path(session_data.repo_path).name
    session_path = Path(session_data.session_path)
    is_worktree = session_data.is_worktree
    backend = get_backend(session_data.backend_name)

    branch = get_branch_name(str(session_path))
    if branch == "HEAD":
        branch = "(detached)"

    console.print(f"\n[bold cyan]Session:[/bold cyan]    {session_name}")
    console.print(f"[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[bold cyan]Backend:[/bold cyan]    {backend.display_name}")
    console.print(
        f"[bold cyan]Type:[/bold cyan]       {'worktree' if is_worktree else 'main repo'}"
    )
    console.print(f"[bold cyan]Branch:[/bold cyan]     {branch}")
    console.print(f"[bold cyan]Path:[/bold cyan]       {session_path}\n")
