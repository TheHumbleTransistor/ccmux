"""Tmux configuration management for ccmux."""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


def get_tmux_config_path() -> Path:
    """Get the path to the tmux.conf file included in the package.

    Returns:
        Path to the tmux.conf file
    """
    return Path(__file__).parent / "tmux.conf"


def apply_tmux_config(session_name: str) -> bool:
    """Apply tmux configuration to a specific session by sourcing the config file.

    Args:
        session_name: Name of the tmux session to configure

    Returns:
        True if configuration was applied successfully, False otherwise
    """
    # Small delay to ensure tmux session is ready
    time.sleep(0.1)

    config_path = get_tmux_config_path()

    if not config_path.exists():
        # Config file not found, but session still works
        return False

    try:
        # Source the config file in the tmux session
        # Using source-file command to load the configuration
        subprocess.run(
            ["tmux", "source-file", str(config_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        # Fail silently - the session still works without custom config
        return False


def apply_outer_session_config(session_name: str) -> bool:
    """Apply minimal outer config via per-session set-option.

    The outer session has no status bar, mouse on, C-Space prefix, and no escape delay.
    Sets the terminal title to a friendly display name derived from the session name.
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
        ("escape-time", "0"),
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
