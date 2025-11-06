"""State management for ccwt - tracks sessions, worktrees, and tmux IDs."""

import json
from pathlib import Path
from typing import Optional


STATE_DIR = Path.home() / ".ccwt"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_SESSION = "ccwt"


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
    tmux_window_id: Optional[str] = None
):
    """Add a worktree to the state."""
    state = load_state()

    # Create session if it doesn't exist
    if session_name not in state["sessions"]:
        state["sessions"][session_name] = {
            "tmux_session_id": tmux_session_id,
            "worktrees": {}
        }

    # Update session's tmux ID if provided
    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    # Add or update worktree
    state["sessions"][session_name]["worktrees"][worktree_name] = {
        "repo_path": repo_path,
        "worktree_path": worktree_path,
        "tmux_window_id": tmux_window_id
    }

    save_state(state)


def remove_worktree(session_name: str, worktree_name: str):
    """Remove a worktree from the state."""
    state = load_state()

    if session_name in state["sessions"]:
        if worktree_name in state["sessions"][session_name]["worktrees"]:
            del state["sessions"][session_name]["worktrees"][worktree_name]

        # Remove session if it has no worktrees
        if not state["sessions"][session_name]["worktrees"]:
            del state["sessions"][session_name]

    save_state(state)


def update_tmux_ids(
    session_name: str,
    worktree_name: str,
    tmux_session_id: Optional[str] = None,
    tmux_window_id: Optional[str] = None
):
    """Update tmux IDs for a worktree."""
    state = load_state()

    if session_name not in state["sessions"]:
        return

    if tmux_session_id:
        state["sessions"][session_name]["tmux_session_id"] = tmux_session_id

    if worktree_name in state["sessions"][session_name]["worktrees"]:
        if tmux_window_id:
            state["sessions"][session_name]["worktrees"][worktree_name]["tmux_window_id"] = tmux_window_id

    save_state(state)


def get_session(session_name: str) -> Optional[dict]:
    """Get a session from state."""
    state = load_state()
    return state["sessions"].get(session_name)


def get_worktree(session_name: str, worktree_name: str) -> Optional[dict]:
    """Get a specific worktree from state."""
    session = get_session(session_name)
    if session:
        return session["worktrees"].get(worktree_name)
    return None


def find_worktree_by_tmux_ids(tmux_session_id: str, tmux_window_id: str) -> Optional[tuple[str, str, dict]]:
    """Find a worktree by its tmux session and window IDs.

    Returns: (session_name, worktree_name, worktree_data) or None
    """
    state = load_state()

    for session_name, session_data in state["sessions"].items():
        if session_data.get("tmux_session_id") == tmux_session_id:
            for worktree_name, worktree_data in session_data["worktrees"].items():
                if worktree_data.get("tmux_window_id") == tmux_window_id:
                    return (session_name, worktree_name, worktree_data)

    return None


def get_all_worktrees(session_name: Optional[str] = None) -> list[dict]:
    """Get all worktrees, optionally filtered by session.

    Returns list of dicts with keys: session, name, repo_path, worktree_path, tmux_window_id
    """
    state = load_state()
    worktrees = []

    sessions_to_query = [session_name] if session_name else state["sessions"].keys()

    for sess_name in sessions_to_query:
        if sess_name not in state["sessions"]:
            continue

        session_data = state["sessions"][sess_name]
        for wt_name, wt_data in session_data["worktrees"].items():
            worktrees.append({
                "session": sess_name,
                "name": wt_name,
                "repo_path": wt_data["repo_path"],
                "worktree_path": wt_data["worktree_path"],
                "tmux_window_id": wt_data.get("tmux_window_id")
            })

    return worktrees
