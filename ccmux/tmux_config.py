"""Tmux configuration management for ccmux."""

import subprocess
import time
from typing import List, Tuple


# Tmux configuration as a list of (option, value) tuples
TMUX_CONFIG: List[Tuple[str, str]] = [
    # Mouse support
    ("mouse", "on"),

    # Status bar color scheme - dark grey theme
    ("status-style", "bg=colour235,fg=colour245"),  # Dark grey background, light grey text
    ("status-left-style", "bg=colour235,fg=colour250"),
    ("status-right-style", "bg=colour235,fg=colour250"),

    # Window status formatting with separators
    ("window-status-format", " #I:#W "),  # Inactive windows: index:name with padding
    ("window-status-current-format", "#[bg=colour237,fg=colour250,bold] #I:#W #[default]"),  # Current window
    ("window-status-separator", "│"),  # Separator between windows

    # Window status styles
    ("window-status-style", "bg=colour235,fg=colour245"),  # Inactive windows
    ("window-status-current-style", "bg=colour237,fg=colour250,bold"),  # Current window

    # Activity and bell monitoring
    ("monitor-activity", "on"),
    ("bell-action", "any"),
    ("visual-activity", "on"),
    ("visual-bell", "off"),

    # Activity and bell styles
    ("window-status-activity-style", "bold,underscore,fg=yellow"),
    ("window-status-bell-style", "bold,reverse,fg=red"),

    # Window titles
    ("set-titles", "on"),
    ("set-titles-string", "tmux:#S · #W"),
]

# Key bindings as a list of (key, command) tuples
TMUX_KEYBINDINGS: List[Tuple[str, str]] = [
    # Clear marks with Ctrl-L
    ("C-l", 'display-message "Clearing marks" \\; set -g monitor-activity off \\; set -g monitor-activity on'),
    # Last window with 'a'
    ("a", "last-window"),
]


def apply_tmux_config(session_name: str) -> bool:
    """Apply tmux configuration to a specific session.

    Args:
        session_name: Name of the tmux session to configure

    Returns:
        True if configuration was applied successfully, False otherwise
    """
    # Small delay to ensure tmux session is ready
    time.sleep(0.1)

    errors = []
    success_count = 0

    # Apply each configuration option
    for option, value in TMUX_CONFIG:
        try:
            result = subprocess.run(
                ["tmux", "set-option", "-t", session_name, "-g", option, value],
                check=True,
                capture_output=True,
                text=True,
            )
            success_count += 1
        except subprocess.CalledProcessError as e:
            errors.append(f"Option {option}: {e.stderr}")

    # Apply key bindings (global, not session-specific)
    for key, command in TMUX_KEYBINDINGS:
        try:
            result = subprocess.run(
                ["tmux", "bind-key", key, command],
                check=True,
                capture_output=True,
                text=True,
            )
            success_count += 1
        except subprocess.CalledProcessError as e:
            errors.append(f"Binding {key}: {e.stderr}")

    # Return True if at least some options were set successfully
    return success_count > 0


def get_tmux_config_content() -> str:
    """Get the tmux configuration as a .tmux.conf file content.

    Returns:
        String containing the tmux configuration in .tmux.conf format
    """
    lines = [
        "# ccmux tmux configuration",
        "# This configuration is automatically applied when creating ccmux sessions",
        "",
        "# Mouse support",
        "set -g mouse on",
        "",
        "# Status bar color scheme - dark grey theme",
    ]

    # Add configuration options
    for option, value in TMUX_CONFIG:
        if option == "mouse":
            continue  # Already added above
        lines.append(f"set -g {option} \"{value}\"")

        # Add section comments
        if option == "status-right-style":
            lines.extend(["", "# Window status formatting with separators"])
        elif option == "window-status-separator":
            lines.extend(["", "# Window status styles"])
        elif option == "window-status-current-style":
            lines.extend(["", "# Activity and bell monitoring"])
        elif option == "visual-bell":
            lines.extend(["", "# Activity and bell styles"])
        elif option == "window-status-bell-style":
            lines.extend(["", "# Window titles"])

    # Add key bindings
    lines.extend(["", "# Key bindings"])
    for key, command in TMUX_KEYBINDINGS:
        # Unescape the command for file output
        clean_command = command.replace("\\;", ";")
        lines.append(f"bind-key {key} {clean_command}")

    return "\n".join(lines) + "\n"