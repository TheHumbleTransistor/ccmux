"""Tmux subprocess wrappers for ccmux."""

import os
import shutil
import subprocess
from typing import Optional


def _terminal_size_flags() -> list[str]:
    """Return [-x, cols, -y, rows] for the current terminal, or [] on failure."""
    try:
        sz = shutil.get_terminal_size()
        return ["-x", str(sz.columns), "-y", str(sz.lines)]
    except OSError:
        return []


def tmux_session_exists(session_name: str) -> bool:
    """Check if a tmux session exists."""
    try:
        subprocess.run(
            ["tmux", "has-session", "-t", f"={session_name}"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def get_current_tmux_window() -> Optional[str]:
    """Get the current tmux window name if running inside tmux."""
    if "TMUX" not in os.environ:
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#W"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_tmux_session() -> Optional[str]:
    """Get the current tmux session name if running inside tmux."""
    if "TMUX" not in os.environ:
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_tmux_windows(session_name: str) -> list[str]:
    """Get all window names in a tmux session."""
    if not tmux_session_exists(session_name):
        return []
    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session_name, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []


def is_window_active_in_session(session_name: str, tmux_window_id: Optional[str]) -> bool:
    """Check if a tmux window ID exists in a specific session."""
    if not tmux_window_id or not tmux_session_exists(session_name):
        return False
    try:
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session_name, "-F", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
        window_ids = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return tmux_window_id in window_ids
    except subprocess.CalledProcessError:
        return False


def kill_tmux_session(name: str) -> bool:
    """Kill a tmux session by exact name. Returns True on success."""
    if not tmux_session_exists(name):
        return False
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", f"={name}"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def kill_tmux_window(target: str) -> bool:
    """Kill a tmux window. Target can be window_id or session:window."""
    try:
        subprocess.run(
            ["tmux", "kill-window", "-t", target],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def create_tmux_session(session: str, window: str, cwd: str, cmd: str) -> Optional[str]:
    """Create a new tmux session. Returns window_id or None."""
    try:
        result = subprocess.run(
            [
                "tmux", "new-session",
                "-d",
                *_terminal_size_flags(),
                "-s", session,
                "-n", window,
                "-c", cwd,
                "-P", "-F", "#{window_id}",
                cmd,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def create_tmux_window(session: str, window: str, cwd: str, cmd: str) -> Optional[str]:
    """Create a new window in an existing session. Returns window_id or None."""
    try:
        result = subprocess.run(
            [
                "tmux", "new-window",
                "-t", session,
                "-n", window,
                "-c", cwd,
                "-P", "-F", "#{window_id}",
                cmd,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_session_id(session: str) -> Optional[str]:
    """Get the tmux session ID (e.g. '$0') for a session name."""
    try:
        return subprocess.run(
            ["tmux", "display-message", "-t", session, "-p", "#{session_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def select_window(session: str, window: str) -> bool:
    """Select a window in a tmux session."""
    try:
        subprocess.run(
            ["tmux", "select-window", "-t", f"{session}:{window}"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def rename_tmux_window(target: str, new_name: str) -> bool:
    """Rename a tmux window."""
    try:
        subprocess.run(
            ["tmux", "rename-window", "-t", target, new_name],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def kill_all_ccmux_sessions(session: str, outer: str, inner: str, bash: str) -> None:
    """Kill outer, inner, and bash sessions in safe order.

    Outer first (display), inner second, bash last (user may be running from bash).
    """
    kill_tmux_session(outer)
    kill_tmux_session(inner)
    kill_tmux_session(bash)


def set_session_option(session: str, option: str, value: str) -> bool:
    """Set a tmux session option. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "set-option", "-t", session, option, value],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def set_window_option(target: str, option: str, value: str) -> bool:
    """Set a tmux window option. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "set-option", "-w", "-t", target, option, value],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def create_session_simple(name: str, cmd: str) -> bool:
    """Create a detached tmux session (no window name, cwd, or print). Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "new-session", "-d", *_terminal_size_flags(), "-s", name, cmd],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def split_window(target: str, direction: str, size: str, cmd: str) -> bool:
    """Split a tmux pane. direction is '-v' or '-h'. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "split-window", "-t", target, direction, "-l", size, cmd],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def set_hook(target: str, hook: str, cmd: str) -> bool:
    """Set a tmux hook on a session. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "set-hook", "-t", target, hook, cmd],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def unset_hook(target: str, hook: str) -> bool:
    """Remove a tmux hook from a session. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "set-hook", "-u", "-t", target, hook],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def select_pane(target: str) -> bool:
    """Select a tmux pane. Returns True on success."""
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", target],
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def detach_client(session: Optional[str] = None, client_tty: Optional[str] = None) -> None:
    """Detach a tmux client. Specify session (-s) to detach all, or client_tty (-t) for one."""
    cmd = ["tmux", "detach-client"]
    if session:
        cmd.extend(["-s", session])
    elif client_tty:
        cmd.extend(["-t", client_tty])
    subprocess.run(cmd, check=True, capture_output=True)


def list_clients(session: str) -> list[str]:
    """List client TTYs attached to a tmux session."""
    result = subprocess.run(
        ["tmux", "list-clients", "-t", session, "-F", "#{client_tty}"],
        capture_output=True, text=True, check=True,
    )
    return [c for c in result.stdout.strip().split("\n") if c]
