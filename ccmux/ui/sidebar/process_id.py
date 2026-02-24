"""PID file management for sidebar processes."""

import os
from pathlib import Path

SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"


def write_pid_file() -> Path:
    """Write current PID to tracking directory. Returns the pid file path."""
    SIDEBAR_PIDS_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = SIDEBAR_PIDS_DIR / f"{os.getpid()}.pid"
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid_file() -> None:
    """Remove current PID file on exit."""
    pid_file = SIDEBAR_PIDS_DIR / f"{os.getpid()}.pid"
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
