"""State management for ccmux - tracks sessions and tmux IDs."""

from ccmux.state.session import Session, WorktreeSession, MainRepoSession
from ccmux.state.store import (
    add_session,
    remove_session,
    get_session,
    get_all_sessions,
    find_session_by_tmux_ids,
    rename_session,
    find_main_repo_session,
    find_session_by_path,
    update_tmux_ids,
    update_session,
    STATE_DIR,
    STATE_FILE,
)

__all__ = [
    "Session",
    "WorktreeSession",
    "MainRepoSession",
    "add_session",
    "remove_session",
    "get_session",
    "get_all_sessions",
    "find_session_by_tmux_ids",
    "rename_session",
    "find_main_repo_session",
    "find_session_by_path",
    "update_tmux_ids",
    "update_session",
    "STATE_DIR",
    "STATE_FILE",
]
