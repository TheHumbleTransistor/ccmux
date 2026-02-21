"""PID file management for sidebar processes."""

import os
from pathlib import Path

SIDEBAR_PIDS_DIR = Path.home() / ".ccmux" / "sidebar_pids"


def _pid_dir(session: str) -> Path:
    return SIDEBAR_PIDS_DIR / session


def write_pid_file(session: str) -> Path:
    """Write current PID to tracking directory. Returns the pid file path."""
    pid_dir = _pid_dir(session)
    pid_dir.mkdir(parents=True, exist_ok=True)
    pid_file = pid_dir / f"{os.getpid()}.pid"
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid_file(session: str) -> None:
    """Remove current PID file on exit."""
    pid_file = _pid_dir(session) / f"{os.getpid()}.pid"
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
