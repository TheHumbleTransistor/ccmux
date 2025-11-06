"""State management for ccmux - tracks sessions, instances, and tmux IDs."""

import json
from pathlib import Path
from typing import Optional


STATE_DIR = Path.home() / ".ccmux"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_SESSION = "ccmux"


def _ensure_state_dir():
    """Ensure the state directory exists."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    """Load state from disk, or return empty state if file doesn't exist."""
    if not STATE_FILE.exists():
        return {
            "sessions": {},
            "default_session": DEFAULT_SESSION
        }

    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupted, return empty state
        return {
            "sessions": {},
            "default_session": DEFAULT_SESSION
        }


def save_state(state: dict):
    """Save state to disk."""
    _ensure_state_dir()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def add_worktree(
    session_name: str,
    worktree_name: str,
    repo_path: str,
    worktree_path: str,
    tmux_session_id: Optional[str] = None,
    tmux_window_id: Optional[str] = None,
    is_worktree: bool = True
):
    """Add an instance to the state (can be main repo or worktree)."""
    state = load_state()

    # Create session if it doesn't exist
    if session_name not in state["sessions"]:
        state["sessions"][session_name] = {
            "tmux_session_id": tmux_session_id,
            "instances": {}
        }
    # Handle migration from old "worktrees" key to new "instances" key
    elif "worktrees" in state["sessions"][session_name]:
        state["sessions"][session_name]["instances"] = state["sessions"][session_name].pop("worktrees", {})

    # Update session's tmux ID if provided
    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    # Add or update instance
    state["sessions"][session_name]["instances"][worktree_name] = {
        "repo_path": repo_path,
        "instance_path": worktree_path,
        "is_worktree": is_worktree,
        "tmux_window_id": tmux_window_id
    }

    save_state(state)


def remove_worktree(session_name: str, worktree_name: str):
    """Remove an instance from the state."""
    state = load_state()

    if session_name in state["sessions"]:
        # Handle both old "worktrees" and new "instances" keys
        instances_key = "instances" if "instances" in state["sessions"][session_name] else "worktrees"

        if worktree_name in state["sessions"][session_name][instances_key]:
            del state["sessions"][session_name][instances_key][worktree_name]

        # Remove session if it has no instances
        if not state["sessions"][session_name][instances_key]:
            del state["sessions"][session_name]

    save_state(state)


def update_tmux_ids(
    session_name: str,
    worktree_name: str,
    tmux_session_id: Optional[str] = None,
    tmux_window_id: Optional[str] = None
):
    """Update tmux IDs for an instance."""
    state = load_state()

    if session_name not in state["sessions"]:
        return

    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    # Handle both old "worktrees" and new "instances" keys
    instances_key = "instances" if "instances" in state["sessions"][session_name] else "worktrees"

    if worktree_name in state["sessions"][session_name][instances_key]:
        if tmux_window_id:
            state["sessions"][session_name][instances_key][worktree_name]["tmux_window_id"] = tmux_window_id

    save_state(state)


def get_session(session_name: str) -> Optional[dict]:
    """Get a session from state."""
    state = load_state()
    return state["sessions"].get(session_name)


def get_worktree(session_name: str, worktree_name: str) -> Optional[dict]:
    """Get a specific instance from state."""
    session = get_session(session_name)
    if session:
        # Handle both old "worktrees" and new "instances" keys
        instances = session.get("instances", session.get("worktrees", {}))
        return instances.get(worktree_name)
    return None


def find_worktree_by_tmux_ids(tmux_session_id: str, tmux_window_id: str) -> Optional[tuple[str, str, dict]]:
    """Find an instance by its tmux session and window IDs.

    Returns: (session_name, instance_name, instance_data) or None
    """
    state = load_state()

    for session_name, session_data in state["sessions"].items():
        if session_data.get("tmux_session_id") == tmux_session_id:
            # Handle both old "worktrees" and new "instances" keys
            instances = session_data.get("instances", session_data.get("worktrees", {}))
            for instance_name, instance_data in instances.items():
                if instance_data.get("tmux_window_id") == tmux_window_id:
                    return (session_name, instance_name, instance_data)

    return None


def get_all_worktrees(session_name: Optional[str] = None) -> list[dict]:
    """Get all instances, optionally filtered by session.

    Returns list of dicts with keys: session, name, repo_path, instance_path, is_worktree, tmux_window_id
    """
    state = load_state()
    instances_list = []

    sessions_to_query = [session_name] if session_name else state["sessions"].keys()

    for sess_name in sessions_to_query:
        if sess_name not in state["sessions"]:
            continue

        session_data = state["sessions"][sess_name]
        # Handle both old "worktrees" and new "instances" keys
        instances = session_data.get("instances", session_data.get("worktrees", {}))
        for inst_name, inst_data in instances.items():
            instances_list.append({
                "session": sess_name,
                "name": inst_name,
                "repo_path": inst_data["repo_path"],
                "instance_path": inst_data.get("instance_path", inst_data.get("worktree_path")),
                "is_worktree": inst_data.get("is_worktree", True),  # Default to True for backward compat
                "tmux_window_id": inst_data.get("tmux_window_id")
            })

    return instances_list


def find_main_repo_instance(repo_path: str, session_name: Optional[str] = None) -> Optional[dict]:
    """Find if a main repo instance already exists for the given repository.

    Returns the instance data if found, None otherwise.
    """
    instances = get_all_worktrees(session_name)
    for instance in instances:
        if instance["repo_path"] == repo_path and not instance.get("is_worktree", True):
            return instance
    return None
