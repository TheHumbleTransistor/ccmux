"""Detect ccmux version upgrades and prompt to kill stale tmux sessions."""

from ccmux import __version__
from ccmux.display import console
from ccmux.state import get_all_sessions, get_state_version, set_state_version


def check_version_mismatch() -> None:
    """Check if the running ccmux version differs from the stamped state version.

    If stale tmux sessions are detected after an upgrade, prompts the user to
    kill them so hooks and configuration are refreshed on next activation.
    """
    stored = get_state_version()

    # Exact match — nothing to do
    if stored == __version__:
        return

    # No stored version and no sessions → first run, just stamp
    if stored is None and not get_all_sessions():
        set_state_version(__version__)
        return

    # Mismatch (or no stored version with existing sessions).
    # Check whether ccmux tmux sessions are actually running.
    from ccmux.naming import BASH_SESSION, INNER_SESSION, OUTER_SESSION
    from ccmux.tmux_ops import tmux_session_exists

    if not tmux_session_exists(INNER_SESSION):
        # No live tmux — just stamp the new version silently
        set_state_version(__version__)
        return

    # Active tmux sessions from a different version — prompt user
    from rich.prompt import Confirm

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
        "Running tmux sessions use outdated hooks and may behave unexpectedly."
    )
    console.print(
        "Killing them is safe — sessions will be recreated on "
        "[bold]ccmux new[/bold] / [bold]ccmux activate[/bold].\n"
    )

    if Confirm.ask("Kill stale ccmux tmux sessions?", default=True):
        from ccmux.tmux_ops import kill_all_ccmux_sessions

        kill_all_ccmux_sessions(OUTER_SESSION, OUTER_SESSION, INNER_SESSION, BASH_SESSION)
        console.print(
            "[green]Done.[/green] Run [bold]ccmux new[/bold] or "
            "[bold]ccmux activate[/bold] to start fresh."
        )
    else:
        console.print(
            "[dim]Keeping existing sessions — behavior may be degraded.[/dim]"
        )

    # Stamp version either way so the prompt only fires once per upgrade
    set_state_version(__version__)
