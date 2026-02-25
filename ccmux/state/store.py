"""State I/O and CRUD functions for ccmux."""

import json
from pathlib import Path
from typing import Optional

from ccmux.state.session import Session


STATE_DIR = Path.home() / ".ccmux"
STATE_FILE = STATE_DIR / "state.json"


def _ensure_state_dir():
    """Ensure the state directory exists."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict:
    """Load raw state from disk, or return empty state if file doesn't exist.

    Handles migration from old nested format (sessions.default.instances)
    to the new flat format (sessions at top level).
    """
    if not STATE_FILE.exists():
        return {
            "sessions": {},
        }

    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            "sessions": {},
        }

    # Migrate old nested format: sessions.default.instances -> sessions
    if "sessions" in data:
        sessions = data["sessions"]
        # Detect old format: sessions contain a key with "instances" sub-dict
        for session_name, session_data in list(sessions.items()):
            if isinstance(session_data, dict) and "instances" in session_data:
                # Old format: flatten by lifting instances up
                old_tmux_id = session_data.get("tmux_session_id")
                for inst_name, inst_data in session_data["instances"].items():
                    # Rename instance_path -> session_path if needed
                    if "instance_path" in inst_data and "session_path" not in inst_data:
                        inst_data["session_path"] = inst_data.pop("instance_path")
                    sessions[inst_name] = inst_data
                del sessions[session_name]
                # Preserve tmux_session_id at top level
                if old_tmux_id:
                    data["tmux_session_id"] = old_tmux_id
                break  # Only one old session ("default") expected

    # Backfill id for sessions that lack it
    needs_backfill = any(
        "id" not in sess_data
        for sess_data in data.get("sessions", {}).values()
    )
    if needs_backfill:
        next_id = data.get("next_id", 1)
        for sess_data in data["sessions"].values():
            if "id" not in sess_data:
                sess_data["id"] = next_id
                next_id += 1
        data["next_id"] = next_id

    return data


def _save_raw(state: dict):
    """Save raw state to disk."""
    _ensure_state_dir()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# --- Session CRUD ---

def add_session(
    session_name: str,
    repo_path: str,
    session_path: str,
    tmux_session_id: Optional[str] = None,
    tmux_cc_window_id: Optional[str] = None,
    tmux_bash_window_id: Optional[str] = None,
    is_worktree: bool = True,
    claude_session_id: Optional[str] = None,
):
    """Add a session to the state (can be main repo or worktree)."""
    state = _load_raw()

    if tmux_session_id:
        state["tmux_session_id"] = tmux_session_id

    session_id = state.get("next_id", 1)
    state["next_id"] = session_id + 1

    sess_data = {
        "repo_path": repo_path,
        "session_path": session_path,
        "is_worktree": is_worktree,
        "tmux_window_ids": {
            "claude_code": tmux_cc_window_id,
            "bash_terminal": tmux_bash_window_id,
        },
        "id": session_id,
    }
    if claude_session_id:
        sess_data["claude_session_id"] = claude_session_id

    state["sessions"][session_name] = sess_data

    _save_raw(state)


def remove_session(session_name: str):
    """Remove a session from the state."""
    state = _load_raw()

    sessions = state.get("sessions", {})
    if session_name in sessions:
        del sessions[session_name]

    _save_raw(state)


def update_tmux_ids(
    session_name: str,
    tmux_session_id: Optional[str] = None,
    tmux_cc_window_id: Optional[str] = None,
    tmux_bash_window_id: Optional[str] = None,
):
    """Update tmux IDs for a session."""
    state = _load_raw()

    if tmux_session_id:
        state["tmux_session_id"] = tmux_session_id

    sessions = state.get("sessions", {})
    if session_name in sessions:
        if tmux_cc_window_id or tmux_bash_window_id:
            window_ids = sessions[session_name].get("tmux_window_ids", {})
            if tmux_cc_window_id:
                window_ids["claude_code"] = tmux_cc_window_id
            if tmux_bash_window_id:
                window_ids["bash_terminal"] = tmux_bash_window_id
            sessions[session_name]["tmux_window_ids"] = window_ids

    _save_raw(state)


def clear_tmux_window_ids(session_name: str) -> bool:
    """Clear both window IDs for a session. Returns True if found."""
    state = _load_raw()
    sessions = state.get("sessions", {})
    if session_name not in sessions:
        return False
    sessions[session_name]["tmux_window_ids"] = {
        "claude_code": None,
        "bash_terminal": None,
    }
    _save_raw(state)
    return True


def get_session(session_name: str) -> Optional[Session]:
    """Get a specific session from state.

    Returns a Session object, or None if not found.
    """
    state = _load_raw()
    raw = state["sessions"].get(session_name)
    if raw is None:
        return None
    return Session.from_dict(session_name, raw)


def get_all_sessions() -> list[Session]:
    """Get all sessions.

    Returns list of Session objects.
    """
    state = _load_raw()
    sessions_list = []

    for name, data in state.get("sessions", {}).items():
        sess = Session.from_dict(name, data)
        sessions_list.append(sess)

    return sessions_list


def find_session_by_tmux_ids(tmux_session_id: str, tmux_window_id: str) -> Optional[tuple[str, Session]]:
    """Find a session by its tmux session and window IDs.

    Returns: (session_name, Session) or None
    """
    state = _load_raw()

    if state.get("tmux_session_id") != tmux_session_id:
        return None

    for name, data in state.get("sessions", {}).items():
        sess = Session.from_dict(name, data)
        if sess.tmux_cc_window_id == tmux_window_id:
            return (name, sess)

    return None


def rename_session(old_name: str, new_name: str) -> bool:
    """Rename a session.

    Returns True if the rename succeeded, False if the session was not found
    or new_name already exists.
    """
    s = _load_raw()

    sessions = s.get("sessions", {})

    if old_name not in sessions:
        return False
    if new_name in sessions:
        return False

    sessions[new_name] = sessions.pop(old_name)

    _save_raw(s)
    return True


def update_session(session_name: str, **fields) -> bool:
    """Update fields on a session in state.

    Returns True if the session was found and updated, False otherwise.
    """
    s = _load_raw()

    sessions = s.get("sessions", {})

    if session_name not in sessions:
        return False

    sessions[session_name].update(fields)
    _save_raw(s)
    return True


def find_main_repo_session(repo_path: str) -> Optional[Session]:
    """Find if a main repo session already exists for the given repository.

    Returns the Session if found, None otherwise.
    """
    sessions = get_all_sessions()
    for sess in sessions:
        if sess.repo_path == repo_path and not sess.is_worktree:
            return sess
    return None


def find_session_by_path(path: str) -> Optional[tuple[str, Session]]:
    """Find session whose session_path is a prefix of the given path.
    Returns the most specific (longest) match: (session_name, Session) or None.
    """
    sessions = get_all_sessions()
    best: Optional[tuple[str, Session]] = None
    best_len = -1
    for sess in sessions:
        sp = sess.session_path.rstrip("/")
        if path == sp or path.startswith(sp + "/"):
            if len(sp) > best_len:
                best_len = len(sp)
                best = (sess.name, sess)
    return best
