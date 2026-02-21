"""Sidebar data layer — snapshot building and tmux queries (no Textual imports)."""

import asyncio
import subprocess
from pathlib import Path

from ccmux import state


def group_by_repo(snapshot: list[tuple]) -> dict[str, list[tuple]]:
    """Group snapshot entries by repo name (first element of each tuple)."""
    repos: dict[str, list[tuple]] = {}
    for entry in snapshot:
        repos.setdefault(entry[0], []).append(entry)
    for entries in repos.values():
        entries.sort(key=lambda e: (e[2] != "main", e[1]))
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


async def build_snapshot(session_name: str) -> list[tuple]:
    """Build a comparable snapshot of the current instance state."""
    instances = state.get_all_instances(session_name)
    if not instances:
        return []

    window_flags = await get_tmux_window_flags(session_name)
    current_instance = await get_current_instance_name(session_name)

    snapshot = []
    for inst in instances:
        repo_name = Path(inst.repo_path).name
        wid = inst.tmux_window_id
        is_active = wid in window_flags
        is_current = inst.name == current_instance
        inst_type = inst.instance_type
        alert_state = resolve_alert_state(window_flags.get(wid))
        snapshot.append((repo_name, inst.name, inst_type, is_active, is_current, alert_state))
    return snapshot
