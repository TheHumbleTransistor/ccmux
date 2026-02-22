"""Sidebar data layer — snapshot building and tmux queries (no Textual imports)."""

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ccmux import state


@dataclass(frozen=True, slots=True)
class InstanceSnapshot:
    repo_name: str
    instance_name: str
    instance_type: str
    is_active: bool
    is_current: bool
    alert_state: str | None
    branch: str | None = None
    short_sha: str = ""
    lines_added: int = 0
    lines_removed: int = 0


def group_by_repo(snapshot: list[InstanceSnapshot]) -> dict[str, list[InstanceSnapshot]]:
    """Group snapshot entries by repo name."""
    repos: dict[str, list[InstanceSnapshot]] = {}
    for entry in snapshot:
        repos.setdefault(entry.repo_name, []).append(entry)
    for entries in repos.values():
        entries.sort(key=lambda e: (e.instance_type != "main", e.instance_name))
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


async def get_current_window_id(session_name: str) -> str | None:
    """Query the inner tmux session for the currently active window ID."""
    inner = f"{session_name}-inner"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "display-message", "-t", inner, "-p", "#{window_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


async def get_current_instance_name(session_name: str) -> str | None:
    """Resolve the current instance name by dynamically finding our window."""
    window_id = await get_current_window_id(session_name)
    if not window_id:
        return None
    session_obj = state.get_session(session_name)
    if not session_obj:
        return None
    for inst_name, inst in session_obj.instances.items():
        if inst.tmux_window_id == window_id:
            return inst_name
    return None


async def get_tmux_window_flags(session_name: str) -> dict[str, dict[str, bool]]:
    """Get window IDs and their bell/activity/silence flags from inner session."""
    inner = f"{session_name}-inner"
    fmt = "#{window_id}|#{@ccmux_bell}|#{window_activity_flag}|#{window_silence_flag}"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["tmux", "list-windows", "-t", inner, "-F", fmt],
            capture_output=True,
            text=True,
            check=True,
        )
        flags: dict[str, dict[str, bool]] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                wid = parts[0]
                flags[wid] = {
                    "bell": parts[1] == "1",
                    "activity": parts[2] == "1",
                    "silence": parts[3] == "1",
                }
        return flags
    except subprocess.CalledProcessError:
        return {}


async def get_git_info(instance_path: str) -> tuple[str | None, str, int, int]:
    """Get git branch, short SHA, and diff stats for an instance path.

    Returns (branch, short_sha, lines_added, lines_removed).
    branch is None when in detached HEAD state.
    """
    branch: str | None = None
    short_sha = ""
    try:
        branch_result = await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run,
                ["git", "-C", instance_path, "rev-parse", "--abbrev-ref", "HEAD"],
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
                ["git", "-C", instance_path, "rev-parse", "--short", "HEAD"],
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
                ["git", "-C", instance_path, "diff", "HEAD", "--shortstat"],
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


async def build_snapshot(session_name: str) -> list[InstanceSnapshot]:
    """Build a comparable snapshot of the current instance state."""
    instances = state.get_all_instances(session_name)
    if not instances:
        return []

    window_flags_task = get_tmux_window_flags(session_name)
    current_instance_task = get_current_instance_name(session_name)
    git_tasks = [get_git_info(inst.instance_path) for inst in instances]

    results = await asyncio.gather(
        window_flags_task, current_instance_task, *git_tasks,
    )
    window_flags = results[0]
    current_instance = results[1]
    git_infos = results[2:]

    snapshot = []
    for inst, (branch, short_sha, added, removed) in zip(instances, git_infos):
        repo_name = Path(inst.repo_path).name
        wid = inst.tmux_window_id
        is_active = wid in window_flags
        is_current = inst.name == current_instance
        inst_type = inst.instance_type
        alert_state = resolve_alert_state(window_flags.get(wid))
        snapshot.append(InstanceSnapshot(
            repo_name=repo_name,
            instance_name=inst.name,
            instance_type=inst_type,
            is_active=is_active,
            is_current=is_current,
            alert_state=alert_state,
            branch=branch,
            short_sha=short_sha,
            lines_added=added,
            lines_removed=removed,
        ))
    return snapshot
