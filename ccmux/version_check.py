"""Detect whether ccmux tmux sessions are running on an outdated version."""

from ccmux import __version__
from ccmux.naming import INNER_SESSION
from ccmux.state import get_tmux_session_version
from ccmux.tmux_ops import tmux_session_exists


def stale_sessions_running() -> bool:
    """Return True if ccmux tmux sessions are running on an outdated version."""
    # Ground truth first — is anything actually running?
    if not tmux_session_exists(INNER_SESSION):
        return False
    # Running session exists — is it from a different version?
    stored = get_tmux_session_version()
    return stored != __version__
