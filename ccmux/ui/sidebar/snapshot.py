"""Sidebar data layer — snapshot building and tmux queries (no Textual imports)."""

import asyncio
import logging
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ccmux import state
from ccmux.naming import INNER_SESSION

_log = logging.getLogger("ccmux.sidebar")

ACTIVITY_TIMEOUT = 5  # maximum seconds since last output to consider "recently active"


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    repo_name: str
    repo_path: str
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
    activity_ts: float = 0.0
    note: str = ""


@dataclass(frozen=True, slots=True)
class DerivedSessionState:
    """Computed session state wrapping a raw snapshot with UI-level status."""

    snapshot: SessionSnapshot
    status: str  # "deactivated" | "idle" | "blocked" | "active"
    has_blocker_alert: bool


def group_by_repo(
    entries: list[DerivedSessionState],
) -> dict[str, list[DerivedSessionState]]:
    """Group derived session entries by full repo path."""
    repos: dict[str, list[DerivedSessionState]] = {}
    for entry in entries:
        repos.setdefault(entry.snapshot.repo_path, []).append(entry)
    for repo_entries in repos.values():
        repo_entries.sort(
            key=lambda d: (d.snapshot.session_type != "main", d.snapshot.session_id),
        )
    return repos


def build_repo_display_names(
    grouped: dict[str, list[DerivedSessionState]],
) -> dict[str, str]:
    """Map repo paths to display names, disambiguating collisions with (2), (3), etc.

    Older repos (lower session IDs) keep the clean name; newer repos get a suffix.
    """
    paths = list(grouped)
    names = {p: Path(p).name for p in paths}
    name_counts = Counter(names.values())
    # Sort by minimum session_id so older repos keep the clean name
    paths_sorted = sorted(grouped, key=lambda p: min(d.snapshot.session_id for d in grouped[p]))
    seen: dict[str, int] = {}
    display: dict[str, str] = {}
    for p in paths_sorted:
        base = names[p]
        if name_counts[base] == 1:
            display[p] = f"{base}/"
        else:
            idx = seen.get(base, 0)
            seen[base] = idx + 1
            display[p] = f"{base}/" if idx == 0 else f"{base}/ ({idx + 1})"
    return display


def resolve_alert_state(flags: dict | None) -> str | None:
    """Determine alert state from window flags (bell > activity)."""
    if not flags:
        return None
    if flags.get("bell"):
        return "bell"
    if flags.get("recently_active"):
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
    """Get window IDs and their bell/activity timestamp + sid from inner session."""
    fmt = "#{window_id}|#{window_bell_flag}|#{window_activity}|#{@ccmux_sid}"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "list-windows", "-t", INNER_SESSION, "-F", fmt],
            capture_output=True,
            text=True,
            check=True,
        )
        now = time.time()
        flags: dict[str, dict] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                wid = parts[0]
                activity_ts = int(parts[2]) if parts[2].isdigit() else 0
                flags[wid] = {
                    "bell": parts[1] == "1",
                    "recently_active": (now - activity_ts) < ACTIVITY_TIMEOUT,
                    "sid": parts[3],
                    "activity_ts": float(activity_ts),
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
    _log.debug("window_flags: %s", window_flags)

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
        activity_ts = wid_flags.get("activity_ts", 0.0) if wid_flags else 0.0
        snapshot.append(SessionSnapshot(
            repo_name=repo_name,
            repo_path=sess.repo_path,
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
            activity_ts=activity_ts,
            note=sess.note or "",
        ))
    return snapshot
