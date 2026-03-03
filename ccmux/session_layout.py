"""Session layout management: sidebar hooks, outer session, bash windows."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from ccmux.display import console
from ccmux.naming import (
    BASH_PANE_HEIGHT,
    BASH_SESSION,
    INNER_SESSION,
    OUTER_SESSION,
    SIDEBAR_WIDTH,
)
from ccmux.tmux_ops import (
    create_session_simple,
    create_tmux_session,
    create_tmux_window,
    get_tmux_windows,
    kill_tmux_session,
    resize_pane,
    select_pane,
    set_hook,
    set_session_option,
    set_window_option,
    split_window,
    tmux_session_exists,
    unset_hook,
)
from ccmux.ui.sidebar.process_id import SIDEBAR_PIDS_DIR
from ccmux.ui.tmux import apply_outer_session_config, apply_server_global_config

HOOKS_DIR = Path.home() / ".ccmux" / "hooks"


# ---------------------------------------------------------------------------
# Sidebar communication
# ---------------------------------------------------------------------------


def notify_sidebars() -> None:
    """Send SIGUSR1 to all active sidebar processes."""
    if not SIDEBAR_PIDS_DIR.is_dir():
        return
    for pid_file in SIDEBAR_PIDS_DIR.iterdir():
        if not pid_file.suffix == ".pid":
            continue
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGUSR1)
        except (ProcessLookupError, ValueError):
            try:
                pid_file.unlink(missing_ok=True)
            except OSError:
                pass
        except PermissionError:
            pass


def install_inner_hook() -> None:
    """Install hooks on the inner session for sidebar refresh and bash sync."""
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    script_path = HOOKS_DIR / "notify-sidebar.sh"

    script_content = _build_hook_script()
    script_path.write_text(script_content)
    script_path.chmod(0o755)

    set_hook(INNER_SESSION, "alert-bell", f"run-shell '{script_path}'")
    set_hook(INNER_SESSION, "after-select-window", f"run-shell '{script_path}'")
    set_hook(INNER_SESSION, "alert-activity", f"run-shell '{script_path}'")


def _build_hook_script() -> str:
    """Build the shell script content for the inner hook."""
    return f"""\
#!/bin/sh
WIN=$(tmux display-message -t "{INNER_SESSION}" -p '#{{window_name}}' 2>/dev/null)
if [ -n "$WIN" ]; then
    if ! tmux select-window -t "{BASH_SESSION}:$WIN" 2>/dev/null; then
        DIR=$(tmux display-message -t "{INNER_SESSION}" -p '#{{pane_current_path}}' 2>/dev/null)
        [ -z "$DIR" ] && DIR="$HOME"
        tmux new-window -t "{BASH_SESSION}" -n "$WIN" -c "$DIR" \
            "export CCMUX_SESSION=$WIN; export COLORTERM=truecolor; while true; do \\$SHELL; done" 2>/dev/null
        tmux set-option -w -t "{BASH_SESSION}:$WIN" window-style 'bg=#1e1e1e' 2>/dev/null
        SID=$(tmux display-message -t "{INNER_SESSION}" -p '#{{@ccmux_sid}}' 2>/dev/null)
        [ -n "$SID" ] && tmux set-option -w -t "{BASH_SESSION}:$WIN" @ccmux_sid "$SID" 2>/dev/null
        tmux select-window -t "{BASH_SESSION}:$WIN" 2>/dev/null
    fi
fi
for f in "$HOME/.ccmux/sidebar_pids"/*.pid; do
    [ -f "$f" ] && kill -USR1 "$(cat "$f")" 2>/dev/null
done
"""


def uninstall_inner_hook() -> None:
    """Remove the alert-bell and after-select-window hooks from the inner session."""
    for hook_name in ("alert-bell", "after-select-window", "alert-activity"):
        unset_hook(INNER_SESSION, hook_name)
    script_path = HOOKS_DIR / "notify-sidebar.sh"
    try:
        script_path.unlink(missing_ok=True)
    except OSError:
        pass
    # Clean up the detach hook and restore default keybinding
    try:
        (HOOKS_DIR / "detach-outer.sh").unlink(missing_ok=True)
    except OSError:
        pass
    _restore_detach_key()


# ---------------------------------------------------------------------------
# Detach helper: correct-terminal detach for nested sessions
# ---------------------------------------------------------------------------


def install_detach_hook() -> None:
    """Install the detach-outer.sh helper script used by the wrapper and keybinding."""
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    script_path = HOOKS_DIR / "detach-outer.sh"
    script_content = f"""\
#!/bin/sh
OUTER="{OUTER_SESSION}"
CLIENT=$(tmux list-clients -t "$OUTER" -F '#{{client_activity}}:#{{client_tty}}' 2>/dev/null \\
    | sort -t: -k1 -rn | head -1 | cut -d: -f2-)
[ -n "$CLIENT" ] && tmux detach-client -t "$CLIENT"
"""
    script_path.write_text(script_content)
    script_path.chmod(0o755)


def _rebind_detach_key() -> None:
    """Rebind prefix-d in the outer session so it detaches the correct terminal.

    Uses ``if-shell`` to check if the active pane belongs to a ccmux inner
    or bash session. If so, runs detach-outer.sh; otherwise, falls through
    to the normal ``detach-client``.
    """
    hook_path = HOOKS_DIR / "detach-outer.sh"
    # The if-shell test checks whether the current session name starts with
    # "ccmux-inner" or "ccmux-bash" (the nested sessions).
    subprocess.run(
        [
            "tmux",
            "bind-key",
            "-T",
            "prefix",
            "d",
            "if-shell",
            f"tmux display-message -p '#{{session_name}}' | grep -qE '^({INNER_SESSION}|{BASH_SESSION})$'",
            f"run-shell '{hook_path}'",
            "detach-client",
        ],
        capture_output=True,
    )


def _restore_detach_key() -> None:
    """Restore prefix-d to the default detach-client behavior."""
    subprocess.run(
        ["tmux", "bind-key", "-T", "prefix", "d", "detach-client"],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Outer session management
# ---------------------------------------------------------------------------


def create_outer_session() -> None:
    """Create the outer tmux session with sidebar, inner client, and bash pane."""
    if tmux_session_exists(OUTER_SESSION) or not tmux_session_exists(INNER_SESSION):
        return

    python_exe = sys.executable or "python3"
    sidebar_cmd = (
        f"TERM=tmux-256color COLORTERM=truecolor {python_exe} -m ccmux.ui.sidebar ; "
        f"echo 'Sidebar exited. Press enter to close.' ; read"
    )

    try:
        create_session_simple(OUTER_SESSION, sidebar_cmd)
        apply_server_global_config()
        apply_outer_session_config(OUTER_SESSION)
        if tmux_session_exists(BASH_SESSION):
            split_window(
                f"{OUTER_SESSION}:0.0",
                "-v",
                str(BASH_PANE_HEIGHT),
                f"/bin/sh -c 'unset TMUX; exec tmux attach -t ={BASH_SESSION}'",
            )
        split_window(
            f"{OUTER_SESSION}:0.0",
            "-h",
            "50%",
            f"/bin/sh -c 'unset TMUX; exec tmux attach -t ={INNER_SESSION}'",
        )
        resize_pane(f"{OUTER_SESSION}:0.0", SIDEBAR_WIDTH)
        install_inner_hook()
        install_detach_hook()
        _rebind_detach_key()
    except Exception as exc:
        print(
            f"ccmux: failed to create outer session '{OUTER_SESSION}': {exc}",
            file=sys.stderr,
        )


def ensure_outer_session() -> None:
    """Ensure the outer session exists; create if missing."""
    if not tmux_session_exists(INNER_SESSION):
        return
    if tmux_session_exists(OUTER_SESSION):
        install_inner_hook()
        install_detach_hook()
        return
    create_outer_session()


def kill_outer_session() -> bool:
    """Kill the outer tmux session and its associated bash session."""
    kill_tmux_session(BASH_SESSION)
    return kill_tmux_session(OUTER_SESSION)


# ---------------------------------------------------------------------------
# Bash window management
# ---------------------------------------------------------------------------


def create_bash_window(session_name: str, working_dir: str) -> str | None:
    """Create a window in the bash session for a session. Returns window ID or None."""
    bash_cmd = (
        f"export CCMUX_SESSION={session_name}; "
        f"export COLORTERM=truecolor; "
        f"while true; do $SHELL; done"
    )
    try:
        if not tmux_session_exists(BASH_SESSION):
            window_id = _create_bash_session(
                BASH_SESSION, session_name, working_dir, bash_cmd
            )
        else:
            if session_name in get_tmux_windows(BASH_SESSION):
                return None
            window_id = create_tmux_window(
                BASH_SESSION, session_name, working_dir, bash_cmd
            )
        set_window_option(
            f"{BASH_SESSION}:{session_name}", "window-style", "bg=#1e1e1e"
        )
        return window_id
    except Exception:
        return None


def _create_bash_session(
    bash: str, session_name: str, working_dir: str, bash_cmd: str
) -> str | None:
    """Create a new bash tmux session with status off and mouse on. Returns window ID."""
    window_id = create_tmux_session(bash, session_name, working_dir, bash_cmd)
    set_session_option(bash, "status", "off")
    set_session_option(bash, "mouse", "on")
    set_session_option(bash, "window-size", "latest")
    return window_id
