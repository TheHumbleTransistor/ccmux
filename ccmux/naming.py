"""Naming conventions, constants, and detection helpers for ccmux sessions."""

import os
import random
import re
import subprocess
from pathlib import Path
from typing import Optional

from ccmux import state
from ccmux.tmux_ops import (
    get_current_tmux_session,
    get_current_tmux_window,
    is_window_active_in_session,
    tmux_session_exists,
)

# Tmux session names (constants — no more parameterized naming)
INNER_SESSION = "ccmux-inner"
BASH_SESSION = "ccmux-bash"
OUTER_SESSION = "ccmux"

# Outer session pane dimensions
SIDEBAR_WIDTH = 41   # 4 chars wider than 37-char CCMUX ASCII art title
BASH_PANE_HEIGHT = 4

ANIMALS = [
    "otter", "lynx", "fox", "wolf", "bear", "wren", "robin", "hawk", "eagle", "falcon",
    "heron", "swan", "crane", "goose", "duck", "loon", "ibis", "kiwi", "dingo", "quokka",
    "bison", "yak", "ibex", "oryx", "okapi", "tapir", "panda", "koala", "wombat",
    "gecko", "skink", "python", "mamba", "cobra", "viper", "boar", "mole", "vole",
    "puma", "jaguar", "leopard", "tiger", "lion", "cheetah", "serval", "caracal", "ocelot",
    "kudu", "eland", "gazelle", "impala", "springbok", "hyena", "dolphin", "orca",
    "beluga", "manatee", "seal", "walrus", "penguin", "salmon", "trout", "sturgeon",
    "carp", "pike", "marlin", "tuna", "halibut", "cod", "owl", "kestrel", "harrier",
    "kite", "buzzard", "condor", "vulture", "beetle", "moth", "ant", "wasp", "bee",
    "dragonfly", "mantis", "beaver", "muskrat", "hare", "rabbit", "pika",
]


def sanitize_name(name: str) -> str:
    """Sanitize a name for use as a branch/worktree name."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9-]+', '-', name)
    name = re.sub(r'^-+|-+$', '', name)
    name = re.sub(r'-{2,}', '-', name)
    return name


def generate_animal_name() -> str:
    """Generate a random animal name."""
    return random.choice(ANIMALS)


def is_session_window_active(
    tmux_window_id: Optional[str], expected_sid: Optional[int] = None,
) -> bool:
    """Check if a session window is active (checks inner session)."""
    return is_window_active_in_session(INNER_SESSION, tmux_window_id, expected_sid=expected_sid)


def detect_current_ccmux_session() -> Optional[tuple[str, "state.Session"]]:
    """Detect the current ccmux session.

    Checks CCMUX_SESSION env var first (set in each pane),
    then falls back to tmux ID matching for backward compat.

    Returns (session_name, Session) or None.
    """
    env_name = os.environ.get("CCMUX_SESSION") or os.environ.get("CCMUX_INSTANCE")
    if env_name:
        sess = state.get_session(env_name)
        if sess:
            return (env_name, sess)

    if "TMUX" not in os.environ:
        return None

    try:
        tmux_session_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        tmux_window_id = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None

    return state.find_session_by_tmux_ids(tmux_session_id, tmux_window_id)


def detect_current_ccmux_session_any() -> Optional[tuple[str, "state.Session"]]:
    """Detect the current ccmux session from inner or bash session.

    First tries detect_current_ccmux_session (env var + inner-session tmux IDs).
    Falls back to bash-session detection and cwd matching.

    Returns (session_name, Session) or None.
    """
    result = detect_current_ccmux_session()
    if result:
        return result

    tmux_session = get_current_tmux_session()
    if tmux_session and tmux_session == BASH_SESSION:
        window_name = get_current_tmux_window()
        if window_name:
            session_data = state.get_session(window_name)
            if session_data:
                return (window_name, session_data)

    try:
        cwd = str(Path.cwd().resolve())
    except OSError:
        return None
    found = state.find_session_by_path(cwd)
    if found:
        return (found[0], found[1])
    return None
