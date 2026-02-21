"""State management for ccmux - tracks sessions, instances, and tmux IDs."""

from ccmux.state.instance import Instance, WorktreeInstance, MainRepoInstance
from ccmux.state.session import Session
from ccmux.state.store import (
    add_instance,
    remove_instance,
    get_instance,
    get_all_instances,
    find_instance_by_tmux_ids,
    get_session,
    rename_session,
    rename_instance,
    remove_session,
    find_main_repo_instance,
    update_tmux_ids,
    get_all_sessions,
    update_instance,
    STATE_DIR,
    STATE_FILE,
    DEFAULT_SESSION,
)

__all__ = [
    "Instance",
    "WorktreeInstance",
    "MainRepoInstance",
    "Session",
    "add_instance",
    "remove_instance",
    "get_instance",
    "get_all_instances",
    "find_instance_by_tmux_ids",
    "get_session",
    "rename_session",
    "rename_instance",
    "remove_session",
    "find_main_repo_instance",
    "update_tmux_ids",
    "get_all_sessions",
    "update_instance",
    "STATE_DIR",
    "STATE_FILE",
    "DEFAULT_SESSION",
]
