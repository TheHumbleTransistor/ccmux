"""Tmux configuration management for ccmux."""

import subprocess
import time
from pathlib import Path
from typing import Optional


# TODO: do we need this function anymore?  if no, let's remove it. Also remove the reference in the project toml file.
def get_tmux_config_path() -> Path:
    """Get the path to the tmux.conf file included in the package.

    Returns:
        Path to the tmux.conf file
    """
    return Path(__file__).parent / "tmux.conf"


# TODO:  we have two inner sessions: the claude code one and the bash terminal.  We need out naming conventions to make that abundantly clear. Update this function name to clarify and also update the names of the tmux sessions.  
def apply_inner_session_config(session_name: str) -> bool:
    """Apply tmux configuration to the inner session via per-session options.

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


# TODO: do we need this function anymore?  if no, let's remove it
def get_tmux_config_content() -> str:
    """Get the tmux configuration as a string.

    Returns:
        String containing the tmux configuration, or error message if not found
    """
    config_path = get_tmux_config_path()

    if not config_path.exists():
        return "# tmux.conf not found in package\n"

    try:
        return config_path.read_text()
    except Exception as e:
        return f"# Error reading tmux.conf: {e}\n"

# TODO: do we need this function anymore?  if no, let's remove it
def export_tmux_config(output_path: Optional[Path] = None) -> tuple[bool, str]:
    """Export the tmux configuration to a file or return its content.

    Args:
        output_path: Optional path to write the config to

    Returns:
        Tuple of (success, message/content)
    """
    content = get_tmux_config_content()

    if output_path:
        try:
            output_path.write_text(content)
            return True, f"Exported tmux configuration to {output_path}"
        except Exception as e:
            return False, f"Error writing file: {e}"
    else:
        return True, content
