#!/usr/bin/env python3
"""Claude Code Multiplexer CLI - Manage multiple Claude Code instances."""

from typing import Annotated, Optional

import cyclopts
from cyclopts import Parameter

from ccmux.instance_ops import (
    do_attach,
    do_detach,
    do_instance_activate,
    do_instance_deactivate,
    do_instance_info,
    do_instance_list,
    do_instance_new,
    do_instance_remove,
    do_instance_rename,
    do_instance_which,
    do_session_kill,
)
from ccmux.session_layout import do_debug_sidebar
from ccmux.display import console

app = cyclopts.App(
    name="ccmux",
    help="Claude Code Multiplexer - Manage multiple Claude Code instances.",
)


@app.default
def instance_info() -> None:
    """Show current instance info, or auto-attach/create if in a git repo."""
    result = do_instance_info()
    if result is None:
        app.help_print([])


@app.command(name="which")
def instance_which() -> None:
    """Print the current instance name (useful for scripting)."""
    do_instance_which()


@app.command(name="new")
def instance_new(
    name: Optional[str] = None,
    *,
    worktree: Annotated[bool, Parameter(name=["-w", "--worktree"])] = False,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Create a new Claude Code instance in main repo or as a git worktree."""
    do_instance_new(name=name, worktree=worktree, yes=yes)


@app.command(name="list")
def instance_list() -> None:
    """List all instances and their tmux session status."""
    do_instance_list()


@app.command(name="rename")
def instance_rename(
    old: Optional[str] = None,
    new: Optional[str] = None,
) -> None:
    """Rename a ccmux instance."""
    do_instance_rename(old=old, new=new)


@app.command(name="attach")
def attach() -> None:
    """Attach to the ccmux tmux session."""
    do_attach()


@app.command(name="activate")
def instance_activate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Activate Claude Code in an instance (useful if tmux window was closed)."""
    do_instance_activate(name=name, yes=yes)


@app.command(name="deactivate")
def instance_deactivate(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Deactivate Claude Code instance(s) by killing tmux window (keeps instance)."""
    do_instance_deactivate(name=name, yes=yes)


@app.command(name="kill")
def session_kill(
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
) -> None:
    """Kill the entire ccmux session."""
    do_session_kill(yes=yes)


@app.command(name="remove")
def instance_remove(
    name: Optional[str] = None,
    *,
    yes: Annotated[bool, Parameter(name=["-y", "--yes"], negative="")] = False,
    all_instances: Annotated[bool, Parameter(name=["--all"], negative="")] = False,
) -> None:
    """Remove instance(s) permanently (deactivates and deletes worktree)."""
    do_instance_remove(name=name, yes=yes, all_instances=all_instances)


@app.command(name="detach")
def detach(
    *,
    all_clients: Annotated[bool, Parameter(name=["-a", "--all"], negative="")] = False,
) -> None:
    """Detach the ccmux tmux session."""
    do_detach(all_clients=all_clients)


@app.command(name="debug")
def debug_sidebar() -> None:
    """Launch a debug session to isolate sidebar rendering issues."""
    do_debug_sidebar()


def main():
    """Main entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        import sys
        sys.exit(130)


if __name__ == "__main__":
    main()
