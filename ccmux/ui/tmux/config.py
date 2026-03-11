"""Tmux configuration management for ccmux."""

import shutil
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


def _detect_clipboard_command() -> str | None:
    """Detect available clipboard command, or None if no clipboard tool found."""
    if shutil.which("xclip"):
        return "xclip -selection clipboard -i"
    if shutil.which("xsel"):
        return "xsel --clipboard --input"
    if shutil.which("wl-copy"):
        return "wl-copy"
    return None


def _apply_copy_mode_config(session_name: str) -> None:
    """Configure vi copy-mode with mouse-drag copy and optional clipboard integration.

    Sets up:
    - vi mode keys for copy-mode navigation
    - Mouse drag auto-copies selection (pane-scoped, avoids cross-pane issues)
    - Double-click selects word, triple-click selects line
    - 'y' in copy-mode yanks selection
    - Pipes to system clipboard when xclip/xsel/wl-copy is available
    """
    clip_cmd = _detect_clipboard_command()

    # Use vi keys in copy mode
    subprocess.run(
        ["tmux", "set-option", "-t", session_name, "mode-keys", "vi"],
        capture_output=True,
    )

    if clip_cmd:
        copy_action = f"send -X copy-pipe-and-cancel '{clip_cmd}'"
    else:
        copy_action = "send -X copy-selection-and-cancel"

    # Mouse drag release → copy (stays within the pane)
    subprocess.run(
        ["tmux", "bind-key", "-T", "copy-mode-vi", "MouseDragEnd1Pane", copy_action],
        capture_output=True,
    )

    # 'y' in copy mode → yank
    subprocess.run(
        ["tmux", "bind-key", "-T", "copy-mode-vi", "y", copy_action],
        capture_output=True,
    )

    # Double-click → select word
    subprocess.run(
        ["tmux", "bind-key", "-T", "copy-mode-vi", "DoubleClick1Pane",
         "select-pane", ";", "send-keys", "-X", "select-word"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "bind-key", "-T", "root", "DoubleClick1Pane",
         "select-pane", "-t=", ";",
         "if-shell", "-F", "#{||:#{pane_in_mode},#{mouse_any_flag}}",
         "send-keys -M",
         "copy-mode -H ; send-keys -X select-word"],
        capture_output=True,
    )

    # Triple-click → select line
    subprocess.run(
        ["tmux", "bind-key", "-T", "copy-mode-vi", "TripleClick1Pane",
         "select-pane", ";", "send-keys", "-X", "select-line"],
        capture_output=True,
    )
    subprocess.run(
        ["tmux", "bind-key", "-T", "root", "TripleClick1Pane",
         "select-pane", "-t=", ";",
         "if-shell", "-F", "#{||:#{pane_in_mode},#{mouse_any_flag}}",
         "send-keys -M",
         "copy-mode -H ; send-keys -X select-line"],
        capture_output=True,
    )


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
        ("activity-action", "off"),
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
        _apply_copy_mode_config(session_name)
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
        _apply_copy_mode_config(session_name)
        return True
    except subprocess.CalledProcessError:
        return False
