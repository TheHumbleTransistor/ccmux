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

# Default session name
DEFAULT_SESSION = "default"

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


def inner_session_name(session: str) -> str:
    """Derive the inner tmux session name."""
    return f"{session}-inner"


def bash_session_name(session: str) -> str:
    """Derive the bash tmux session name."""
    return f"{session}-bash"


def outer_session_name(session: str) -> str:
    """Derive the outer tmux session name."""
    if session == DEFAULT_SESSION:
        return "ccmux"
    return f"ccmux-{session}"


def ccmux_session_from_tmux(tmux_session_name: str) -> str:
    """Strip '-inner' or '-bash' suffix to get the ccmux session name.

    Also reverses the outer_session_name() mapping:
      'ccmux' -> DEFAULT_SESSION, 'ccmux-foo' -> 'foo'.
    """
    if tmux_session_name.endswith("-inner"):
        return tmux_session_name[:-6]
    if tmux_session_name.endswith("-bash"):
        return tmux_session_name[:-5]
    if tmux_session_name == "ccmux":
        return DEFAULT_SESSION
    if tmux_session_name.startswith("ccmux-"):
        return tmux_session_name[6:]
    return tmux_session_name


def is_instance_window_active(session: str, tmux_window_id: Optional[str]) -> bool:
    """Check if an instance window is active (checks inner session)."""
    return is_window_active_in_session(inner_session_name(session), tmux_window_id)


def detect_current_ccmux_instance() -> Optional[tuple[str, str, "state.Instance"]]:
    """Detect the current ccmux instance.

    Checks CCMUX_INSTANCE env var first (set in each pane),
    then falls back to tmux ID matching for backward compat.

    Returns (session_name, instance_name, Instance) or None.
    """
    env_name = os.environ.get("CCMUX_INSTANCE")
    if env_name:
        inst = state.get_instance(env_name, DEFAULT_SESSION)
        if inst:
            return (DEFAULT_SESSION, env_name, inst)

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

    return state.find_instance_by_tmux_ids(tmux_session_id, tmux_window_id)


def detect_current_ccmux_instance_any() -> Optional[tuple[str, str, "state.Instance"]]:
    """Detect the current ccmux instance from inner or bash session.

    First tries detect_current_ccmux_instance (env var + inner-session tmux IDs).
    Falls back to bash-session detection and cwd matching.

    Returns (session_name, instance_name, Instance) or None.
    """
    result = detect_current_ccmux_instance()
    if result:
        return result

    tmux_session = get_current_tmux_session()
    if tmux_session and tmux_session.endswith("-bash"):
        ccmux_session = ccmux_session_from_tmux(tmux_session)
        window_name = get_current_tmux_window()
        if window_name:
            instance_data = state.get_instance(window_name, ccmux_session)
            if instance_data:
                return (ccmux_session, window_name, instance_data)

    try:
        cwd = str(Path.cwd().resolve())
    except OSError:
        return None
    found = state.find_instance_by_path(cwd, DEFAULT_SESSION)
    if found:
        return (DEFAULT_SESSION, found[0], found[1])
    return None
