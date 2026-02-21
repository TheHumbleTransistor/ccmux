"""State I/O and CRUD functions for ccmux."""

import json
from pathlib import Path
from typing import Optional

from ccmux.state.instance import Instance
from ccmux.state.session import Session


STATE_DIR = Path.home() / ".ccmux"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_SESSION = "default"


def _ensure_state_dir():
    """Ensure the state directory exists."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict:
    """Load raw state from disk, or return empty state if file doesn't exist."""
    if not STATE_FILE.exists():
        return {
            "sessions": {},
            "default_session": DEFAULT_SESSION
        }

    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            "sessions": {},
            "default_session": DEFAULT_SESSION
        }


def _save_raw(state: dict):
    """Save raw state to disk."""
    _ensure_state_dir()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# --- Session CRUD ---

def get_session(session_name: str) -> Optional[Session]:
    """Get a session from state.

    Returns a Session object, or None if not found.
    """
    state = _load_raw()
    raw = state["sessions"].get(session_name)
    if raw is None:
        return None
    return Session.from_dict(session_name, raw)


def get_all_sessions() -> list[Session]:
    """Get all sessions.

    Returns a list of Session objects.
    """
    state = _load_raw()
    return [
        Session.from_dict(name, data)
        for name, data in state["sessions"].items()
    ]


def rename_session(old_name: str, new_name: str) -> bool:
    """Rename a session in state.

    Returns True if the rename succeeded, False if old_name not found
    or new_name already exists.
    """
    s = _load_raw()

    if old_name not in s["sessions"]:
        return False
    if new_name in s["sessions"]:
        return False

    s["sessions"][new_name] = s["sessions"].pop(old_name)

    if s.get("default_session") == old_name:
        s["default_session"] = new_name

    _save_raw(s)
    return True


def remove_session(session_name: str) -> bool:
    """Remove an entire session and all its instances from state.

    Returns True if the session was found and removed, False otherwise.
    """
    s = _load_raw()

    if session_name not in s["sessions"]:
        return False

    del s["sessions"][session_name]

    if s.get("default_session") == session_name:
        s["default_session"] = DEFAULT_SESSION

    _save_raw(s)
    return True


# --- Instance CRUD ---

def add_instance(
    session_name: str,
    instance_name: str,
    repo_path: str,
    instance_path: str,
    tmux_session_id: Optional[str] = None,
    tmux_window_id: Optional[str] = None,
    is_worktree: bool = True
):
    """Add an instance to the state (can be main repo or worktree)."""
    state = _load_raw()

    if session_name not in state["sessions"]:
        state["sessions"][session_name] = {
            "tmux_session_id": tmux_session_id,
            "instances": {}
        }

    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    state["sessions"][session_name]["instances"][instance_name] = {
        "repo_path": repo_path,
        "instance_path": instance_path,
        "is_worktree": is_worktree,
        "tmux_window_id": tmux_window_id
    }

    _save_raw(state)


def remove_instance(session_name: str, instance_name: str):
    """Remove an instance from the state."""
    state = _load_raw()

    if session_name in state["sessions"]:
        instances = state["sessions"][session_name].get("instances", {})

        if instance_name in instances:
            del instances[instance_name]

        if not instances:
            del state["sessions"][session_name]

    _save_raw(state)


def update_tmux_ids(
    session_name: str,
    instance_name: str,
    tmux_session_id: Optional[str] = None,
    tmux_window_id: Optional[str] = None
):
    """Update tmux IDs for an instance."""
    state = _load_raw()

    if session_name not in state["sessions"]:
        return

    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    instances = state["sessions"][session_name].get("instances", {})

    if instance_name in instances:
        if tmux_window_id:
            instances[instance_name]["tmux_window_id"] = tmux_window_id

    _save_raw(state)


def get_instance(session_name: str, instance_name: str) -> Optional[Instance]:
    """Get a specific instance from state.

    Returns an Instance object, or None if not found.
    """
    session = get_session(session_name)
    if session:
        return session.instances.get(instance_name)
    return None


def get_all_instances(session_name: Optional[str] = None) -> list[Instance]:
    """Get all instances, optionally filtered by session.

    Returns list of Instance objects with a 'session' attribute set.
    """
    state = _load_raw()
    instances_list = []

    sessions_to_query = [session_name] if session_name else state["sessions"].keys()

    for sess_name in sessions_to_query:
        if sess_name not in state["sessions"]:
            continue

        session = Session.from_dict(sess_name, state["sessions"][sess_name])
        for inst in session.instances.values():
            inst.session = sess_name
            instances_list.append(inst)

    return instances_list


def find_instance_by_tmux_ids(tmux_session_id: str, tmux_window_id: str) -> Optional[tuple[str, str, Instance]]:
    """Find an instance by its tmux session and window IDs.

    Returns: (session_name, instance_name, Instance) or None
    """
    state = _load_raw()

    for session_name, session_data in state["sessions"].items():
        if session_data.get("tmux_session_id") == tmux_session_id:
            session = Session.from_dict(session_name, session_data)
            for instance_name, instance in session.instances.items():
                if instance.tmux_window_id == tmux_window_id:
                    return (session_name, instance_name, instance)

    return None


def rename_instance(session_name: str, old_name: str, new_name: str) -> bool:
    """Rename an instance within a session.

    Returns True if the rename succeeded, False if the instance was not found
    or new_name already exists in the session.
    """
    s = _load_raw()

    if session_name not in s["sessions"]:
        return False

    instances = s["sessions"][session_name].get("instances", {})

    if old_name not in instances:
        return False
    if new_name in instances:
        return False

    instances[new_name] = instances.pop(old_name)

    _save_raw(s)
    return True


def update_instance(session_name: str, instance_name: str, **fields) -> bool:
    """Update fields on an instance in state.

    Returns True if the instance was found and updated, False otherwise.
    """
    s = _load_raw()

    if session_name not in s["sessions"]:
        return False

    instances = s["sessions"][session_name].get("instances", {})

    if instance_name not in instances:
        return False

    instances[instance_name].update(fields)
    _save_raw(s)
    return True


def find_main_repo_instance(repo_path: str, session_name: Optional[str] = None) -> Optional[Instance]:
    """Find if a main repo instance already exists for the given repository.

    Returns the Instance if found, None otherwise.
    """
    instances = get_all_instances(session_name)
    for instance in instances:
        if instance.repo_path == repo_path and not instance.is_worktree:
            return instance
    return None
