"""Sidebar data layer — snapshot building and tmux queries (no Textual imports)."""

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ccmux import state
from ccmux.naming import INNER_SESSION


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    repo_name: str
    session_name: str
    session_type: str
    is_active: bool
    is_current: bool
    alert_state: str | None
    session_id: int = 0
    branch: str | None = None
    short_sha: str = ""
    lines_added: int = 0
    lines_removed: int = 0


def group_by_repo(snapshot: list[SessionSnapshot]) -> dict[str, list[SessionSnapshot]]:
    """Group snapshot entries by repo name."""
    repos: dict[str, list[SessionSnapshot]] = {}
    for entry in snapshot:
        repos.setdefault(entry.repo_name, []).append(entry)
    for entries in repos.values():
        entries.sort(key=lambda e: (e.session_type != "main", e.session_id))
    return repos


def resolve_alert_state(flags: dict[str, bool] | None) -> str | None:
    """Determine alert state from window flags (bell > silence-reset > activity)."""
    if not flags:
        return None
    if flags.get("bell"):
        return "bell"
    if flags.get("silence"):
        return None  # silence overrides activity
    if flags.get("activity"):
        return "activity"
    return None


async def get_current_window_id() -> str | None:
    """Query the inner tmux session for the currently active window ID."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "display-message", "-t", INNER_SESSION, "-p", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


async def get_current_session_name() -> str | None:
    """Resolve the current session name by dynamically finding our window."""
    window_id = await get_current_window_id()
    if not window_id:
        return None
    # Also read @ccmux_sid from the current window for ownership validation
    current_sid: str | None = None
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "display-message", "-t", INNER_SESSION, "-p", "#{@ccmux_sid}"],
            capture_output=True,
            text=True,
            check=True,
        )
        current_sid = result.stdout.strip() or None
    except subprocess.CalledProcessError:
        pass
    sessions = state.get_all_sessions()
    for sess in sessions:
        if sess.tmux_cc_window_id == window_id:
            if current_sid and str(sess.id) != current_sid:
                continue
            return sess.name
    return None


async def get_tmux_window_flags() -> dict[str, dict]:
    """Get window IDs and their bell/activity/silence flags + sid from inner session."""
    fmt = "#{window_id}|#{@ccmux_bell}|#{window_activity_flag}|#{window_silence_flag}|#{@ccmux_sid}"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "list-windows", "-t", INNER_SESSION, "-F", fmt],
            capture_output=True,
            text=True,
            check=True,
        )
        flags: dict[str, dict] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                wid = parts[0]
                flags[wid] = {
                    "bell": parts[1] == "1",
                    "activity": parts[2] == "1",
                    "silence": parts[3] == "1",
                    "sid": parts[4],
                }
        return flags
    except subprocess.CalledProcessError:
        return {}


async def get_git_info(session_path: str) -> tuple[str | None, str, int, int]:
    """Get git branch, short SHA, and diff stats for a session path.

    Returns (branch, short_sha, lines_added, lines_removed).
    branch is None when in detached HEAD state.
    """
    branch: str | None = None
    short_sha = ""
    try:
        branch_result = await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run,
                ["git", "-C", session_path, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, check=True,
            ),
            timeout=5,
        )
        abbrev = branch_result.stdout.strip()
        if abbrev == "HEAD":
            branch = None  # detached HEAD
        else:
            branch = abbrev

        sha_result = await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run,
                ["git", "-C", session_path, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True,
            ),
            timeout=5,
        )
        short_sha = sha_result.stdout.strip()
    except Exception:
        pass

    added, removed = 0, 0
    try:
        diff_result = await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run,
                ["git", "-C", session_path, "diff", "HEAD", "--shortstat"],
                capture_output=True, text=True, check=True,
            ),
            timeout=5,
        )
        stat_line = diff_result.stdout.strip()
        m_add = re.search(r"(\d+) insertion", stat_line)
        m_del = re.search(r"(\d+) deletion", stat_line)
        if m_add:
            added = int(m_add.group(1))
        if m_del:
            removed = int(m_del.group(1))
    except Exception:
        pass

    return branch, short_sha, added, removed


async def build_snapshot() -> list[SessionSnapshot]:
    """Build a comparable snapshot of the current session state."""
    sessions = state.get_all_sessions()
    if not sessions:
        return []

    window_flags_task = get_tmux_window_flags()
    current_session_task = get_current_session_name()
    git_tasks = [get_git_info(sess.session_path) for sess in sessions]

    results = await asyncio.gather(
        window_flags_task, current_session_task, *git_tasks,
    )
    window_flags = results[0]
    current_session = results[1]
    git_infos = results[2:]

    snapshot = []
    for sess, (branch, short_sha, added, removed) in zip(sessions, git_infos):
        repo_name = Path(sess.repo_path).name
        wid = sess.tmux_cc_window_id
        wid_flags = window_flags.get(wid)
        is_active = (
            wid_flags is not None
            and str(sess.id) == wid_flags.get("sid", "")
        )
        is_current = sess.name == current_session
        sess_type = sess.session_type
        alert_state = resolve_alert_state(wid_flags) if is_active else None
        snapshot.append(SessionSnapshot(
            repo_name=repo_name,
            session_name=sess.name,
            session_type=sess_type,
            is_active=is_active,
            is_current=is_current,
            alert_state=alert_state,
            session_id=sess.id,
            branch=branch,
            short_sha=short_sha,
            lines_added=added,
            lines_removed=removed,
        ))
    return snapshot
