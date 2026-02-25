"""Tmux configuration management for ccmux."""

import subprocess
import time


def _wait_for_session(session_name: str, timeout: float = 2.0) -> bool:
    """Poll ``tmux has-session`` until the session exists or *timeout* elapses.

    Polls every 50 ms.  Returns True if the session was found, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
        )
        if result.returncode == 0:
            return True
        time.sleep(0.05)
    return False


def apply_claude_inner_session_config(session_name: str) -> bool:
    """Apply tmux configuration to the Claude Code inner session via per-session options.

    Does NOT set server-global options (default-terminal, terminal-features)
    to avoid corrupting other tmux sessions on the same server.
    """
    _wait_for_session(session_name)

    options = [
        ("mouse", "on"),
        ("status", "off"),
        ("set-titles", "on"),
        ("set-titles-string", "tmux:#S · #W"),
        ("window-size", "latest"),
    ]

    # Window options for activity monitoring (per-session defaults)
    window_options = [
        ("monitor-activity", "on"),
    ]

    # Session options for alert behavior
    session_options_extra = [
        ("visual-activity", "on"),
        ("visual-bell", "off"),
        ("activity-action", "any"),
        ("bell-action", "any"),
    ]

    try:
        for key, val in options + session_options_extra:
            subprocess.run(
                ["tmux", "set-option", "-t", session_name, key, val],
                check=True, capture_output=True,
            )
        for key, val in window_options:
            subprocess.run(
                ["tmux", "set-option", "-w", "-t", session_name, key, val],
                check=True, capture_output=True,
            )
        return True
    except subprocess.CalledProcessError:
        return False


def _terminal_features_contains_rgb() -> bool:
    """Check if ``tmux-256color:RGB`` is already in ``terminal-features``.

    Returns ``False`` (meaning "go ahead and append") when the check itself
    fails — e.g. on older tmux versions that don't support ``show-options``.
    """
    try:
        result = subprocess.run(
            ["tmux", "show-options", "-g", "-v", "terminal-features"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False
        return "tmux-256color:RGB" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def apply_server_global_config() -> bool:
    """Apply server-global tmux options for true-color support."""
    try:
        subprocess.run(
            ["tmux", "set-option", "-g", "default-terminal", "tmux-256color"],
            check=True, capture_output=True,
        )
        if not _terminal_features_contains_rgb():
            subprocess.run(
                ["tmux", "set-option", "-as", "terminal-features",
                 ",tmux-256color:RGB"],
                check=True, capture_output=True,
            )
        return True
    except subprocess.CalledProcessError:
        return False


def apply_outer_session_config(session_name: str) -> bool:
    """Apply minimal outer config via per-session set-option.

    The outer session has no status bar, mouse on, and C-Space prefix.
    Sets the terminal title to a friendly display name derived from the session name.

    Note: These stay programmatic (not in tmux.conf) because ``source-file``
    has no ``-t`` flag — session-scoped options like prefix, border styles,
    and title string require ``set-option -t <session>``.
    """
    if session_name == "ccmux":
        display_title = "CCMUX"
    elif session_name.startswith("ccmux-"):
        display_title = f"CCMUX: {session_name[6:]}"
    else:
        display_title = session_name

    options = [
        ("status", "off"),
        ("mouse", "on"),
        ("prefix", "C-Space"),
        ("pane-border-style", "fg=#333333"),
        ("pane-active-border-style", "fg=#d7af5f"),
        ("set-titles", "on"),
        ("set-titles-string", display_title),
        ("window-size", "latest"),
    ]
    try:
        for key, val in options:
            subprocess.run(
                ["tmux", "set-option", "-t", session_name, key, val],
                check=True, capture_output=True,
            )
        return True
    except subprocess.CalledProcessError:
        return False
