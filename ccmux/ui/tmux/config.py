"""Tmux configuration management for ccmux."""

import subprocess
import time


def apply_claude_inner_session_config(session_name: str) -> bool:
    """Apply tmux configuration to the Claude Code inner session via per-session options.

    Does NOT set server-global options (default-terminal, terminal-features)
    to avoid corrupting other tmux sessions on the same server.
    """
    time.sleep(0.1)

    options = [
        ("mouse", "on"),
        ("status", "off"),
        ("set-titles", "on"),
        ("set-titles-string", "tmux:#S · #W"),
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
