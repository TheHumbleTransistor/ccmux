#!/usr/bin/env python3
"""Claude Code Multiplexer CLI - Manage Claude Code sessions in a shared workspace."""

import shutil
import sys
from typing import Annotated, Optional

import cyclopts
from cyclopts import Parameter
from rich.prompt import Confirm

from ccmux import __version__
from ccmux.display import console
from ccmux.exceptions import CcmuxError, NoSessionsFound
from ccmux.naming import BASH_SESSION, INNER_SESSION, OUTER_SESSION
from ccmux.session_ops import (
    do_attach,
    do_detach,
    do_reload,
    do_session_activate,
    do_session_deactivate,
    do_session_info,
    do_session_kill,
    do_session_list,
    do_session_new,
    do_session_remove,
    do_session_rename,
    do_session_which,
    stale_sessions_running,
)
from ccmux.state import get_tmux_session_version
from ccmux.tmux_ops import check_tmux_installed, kill_all_ccmux_sessions

app = cyclopts.App(
    name="ccmux",
    version=__version__,
    help="Claude Code Multiplexer - Manage Claude Code sessions in a shared workspace.",
)


@app.default
def session_info() -> None:
    """Show current session info, or auto-attach/create if in a git repo."""
    result = do_session_info()
    if result is None:
        app.help_print([])


@app.command(name="which")
def session_which() -> None:
    """Print the current session name (useful for scripting)."""
    do_session_which()


@app.command(name="new")
def session_new(
    path: Optional[str] = None,
    *,
    name: Annotated[Optional[str], Parameter(name=["-n", "--name"])] = None,
    worktree: Annotated[bool, Parameter(name=["-w", "--worktree"])] = False,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Create a new Claude Code session in main repo or as a git worktree."""
    do_session_new(name=name, worktree=worktree, yes=yes, path=path)


@app.command(name="list")
def session_list() -> None:
    """List all sessions in the workspace."""
    do_session_list()


@app.command(name="rename")
def session_rename(
    old: Optional[str] = None,
    new: Optional[str] = None,
) -> None:
    """Rename a session."""
    do_session_rename(old=old, new=new)


@app.command(name="attach")
def attach() -> None:
    """Attach to the workspace. (connects to the ccmux terminal UI via tmux)"""
    do_attach()


@app.command(name="activate")
def session_activate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Activate Claude Code in a session (useful if its window was closed)."""
    do_session_activate(name=name, yes=yes)


@app.command(name="deactivate")
def session_deactivate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Deactivate Claude Code session(s) by closing their windows (keeps session data)."""
    do_session_deactivate(name=name, yes=yes)


@app.command(name="kill")
def session_kill(
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Deactivate all sessions and shut down the workspace."""
    do_session_kill(yes=yes)


@app.command(name="remove")
def session_remove(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
    all_sessions: Annotated[bool, Parameter(name=["--all"], negative="")] = False,
) -> None:
    """Remove session(s) permanently (deactivates and deletes worktree)."""
    do_session_remove(name=name, yes=yes, all_sessions=all_sessions)


@app.command(name="detach")
def detach(
    *,
    all_clients: Annotated[bool, Parameter(name=["-a", "--all"], negative="")] = False,
) -> None:
    """Detach from the workspace. (leaves it running in the background)"""
    do_detach(all_clients=all_clients)


@app.command(name="reload")
def reload() -> None:
    """Reload the workspace UI (kills and recreates the outer tmux session)."""
    do_reload()


def check_claude_installed() -> bool:
    """Check if Claude Code CLI is available on PATH."""
    return shutil.which("claude") is not None


def main():
    """Main entry point for the CLI."""
    if not check_tmux_installed():
        console.print("[red]Error:[/red] tmux is not installed or not found on PATH.", style="bold")
        console.print("\nInstall tmux for your platform:")
        console.print("  Ubuntu/Debian:  sudo apt install tmux")
        console.print("  macOS:          brew install tmux")
        console.print("  Fedora:         sudo dnf install tmux")
        console.print("  Arch:           sudo pacman -S tmux")
        sys.exit(1)

    if not check_claude_installed():
        console.print("[red]Error:[/red] Claude Code is not installed or not found on PATH.", style="bold")
        console.print("\nInstall Claude Code:")
        console.print("  npm install -g @anthropic-ai/claude-code")
        console.print("\nFor more info: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    if stale_sessions_running():
        stored = get_tmux_session_version()
        console.print()
        if stored:
            console.print(
                f"[yellow bold]ccmux upgraded:[/yellow bold] "
                f"{stored} → {__version__}"
            )
        else:
            console.print(
                f"[yellow bold]ccmux upgrade detected[/yellow bold] "
                f"(now {__version__})"
            )
        console.print(
            "The running workspace uses outdated hooks and may behave unexpectedly."
        )
        console.print(
            "Killing them is safe — sessions will be recreated on "
            "[bold]ccmux new[/bold] / [bold]ccmux activate[/bold].\n"
        )

        if Confirm.ask("Shut down the stale workspace?", default=True):
            kill_all_ccmux_sessions(OUTER_SESSION, OUTER_SESSION, INNER_SESSION, BASH_SESSION)
            console.print(
                "[green]Done.[/green] Run [bold]ccmux new[/bold] or "
                "[bold]ccmux activate[/bold] to start fresh."
            )
        else:
            console.print(
                "[dim]Keeping existing workspace — behavior may be degraded.[/dim]"
            )

    try:
        app()
    except NoSessionsFound as e:
        console.print(f"[yellow]{e}[/yellow]")
        if e.hint:
            console.print(f"  {e.hint}")
        sys.exit(0)
    except CcmuxError as e:
        console.print(f"[red]Error:[/red] {e}", style="bold")
        if hasattr(e, "hint") and e.hint:
            console.print(f"  {e.hint}")
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
