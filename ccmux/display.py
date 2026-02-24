"""Rich table and info display for ccmux."""

import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ccmux import state
from ccmux.git_ops import get_branch_name
from ccmux.session_naming import inner_session_name, is_instance_window_active

console = Console()


def display_session_table(session: str) -> None:
    """Display a table of instances."""
    instances = state.get_all_instances(session)

    if not instances:
        console.print(f"\n[yellow]No instances found.[/yellow]")
        return

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
        row = _build_instance_row(session, inst)
        if row["is_active"]:
            active_count += 1
        table.add_row(
            row["repo_name"], inst.name, row["instance_type"],
            row["branch"], row["status"], row["tmux_window_name"],
            str(inst.instance_path),
        )

    console.print()
    console.print(table)
    console.print()

    total_count = len(instances)
    console.print(f"Total: {total_count} instances, {active_count} active, {total_count - active_count} inactive")
    console.print()


def _build_instance_row(session: str, inst) -> dict:
    """Build display data for one instance row."""
    repo_name = Path(inst.repo_path).name
    instance_type = "worktree" if inst.is_worktree else "root"

    branch_raw = get_branch_name(inst.instance_path)
    if branch_raw == "HEAD":
        branch = "[dim](detached)[/dim]"
    elif branch_raw == "(unknown)":
        branch = branch_raw
    else:
        branch = f"[magenta]{branch_raw}[/magenta]"

    tmux_window_name = ""
    status = "[dim]\u25cb Inactive[/dim]"
    is_active = is_instance_window_active(session, inst.tmux_window_id)

    if is_active:
        tmux_window_name = _get_window_display_name(inst.tmux_window_id)
        status = "[green]\u25cf Active[/green]"

    return {
        "repo_name": repo_name,
        "instance_type": instance_type,
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
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def show_instance_info(session_name: str, instance_name: str, instance_data) -> None:
    """Display info about a specific instance."""
    repo_name = Path(instance_data.repo_path).name
    worktree_path = Path(instance_data.instance_path)
    is_worktree = instance_data.is_worktree

    branch = get_branch_name(str(worktree_path))
    if branch == "HEAD":
        branch = "(detached)"

    console.print(f"\n[bold cyan]Instance:[/bold cyan]   {instance_name}")
    console.print(f"[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[bold cyan]Type:[/bold cyan]       {'worktree' if is_worktree else 'main repo'}")
    console.print(f"[bold cyan]Branch:[/bold cyan]     {branch}")
    console.print(f"[bold cyan]Path:[/bold cyan]       {worktree_path}\n")
