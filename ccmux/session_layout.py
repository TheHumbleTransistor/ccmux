"""Session layout management: sidebar hooks, outer session, bash windows, debug."""

import os
import signal
import sys
from pathlib import Path
from typing import Optional

from ccmux.display import console
from ccmux.session_naming import (
    BASH_PANE_HEIGHT,
    bash_session_name,
    inner_session_name,
    outer_session_name,
)
from ccmux.tmux_ops import (
    create_session_simple,
    create_tmux_session,
    create_tmux_window,
    get_tmux_windows,
    kill_tmux_session,
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

def notify_sidebars(session: str) -> None:
    """Send SIGUSR1 to all active sidebar processes for a session."""
    pid_dir = SIDEBAR_PIDS_DIR / session
    if not pid_dir.is_dir():
        return
    for pid_file in pid_dir.iterdir():
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


def install_inner_hook(session: str) -> None:
    """Install hooks on the inner session for sidebar refresh and bash sync."""
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    script_path = HOOKS_DIR / f"notify-sidebar-{session}.sh"
    inner = inner_session_name(session)
    bash = bash_session_name(session)

    script_content = _build_hook_script(inner, bash, session)
    script_path.write_text(script_content)
    script_path.chmod(0o755)

    set_hook(inner, "alert-bell",
             f"set -w @ccmux_bell 1 ; run-shell '{script_path}'")
    set_hook(inner, "after-select-window",
             f"set -w @ccmux_bell 0 ; run-shell '{script_path}'")


def _build_hook_script(inner: str, bash: str, session: str) -> str:
    """Build the shell script content for the inner hook."""
    return f"""\
#!/bin/sh
WIN=$(tmux display-message -t "{inner}" -p '#{{window_name}}' 2>/dev/null)
if [ -n "$WIN" ]; then
    if ! tmux select-window -t "{bash}:$WIN" 2>/dev/null; then
        DIR=$(tmux display-message -t "{inner}" -p '#{{pane_current_path}}' 2>/dev/null)
        [ -z "$DIR" ] && DIR="$HOME"
        tmux new-window -t "{bash}" -n "$WIN" -c "$DIR" \
            "export CCMUX_INSTANCE=$WIN; export COLORTERM=truecolor; while true; do \\$SHELL; done" 2>/dev/null
        tmux set-option -w -t "{bash}:$WIN" window-style 'bg=#1e1e1e' 2>/dev/null
        tmux select-window -t "{bash}:$WIN" 2>/dev/null
    fi
fi
for f in "$HOME/.ccmux/sidebar_pids/{session}"/*.pid; do
    [ -f "$f" ] && kill -USR1 "$(cat "$f")" 2>/dev/null
done
"""


def uninstall_inner_hook(session: str) -> None:
    """Remove the alert-bell and after-select-window hooks from the inner session."""
    inner = inner_session_name(session)
    for hook_name in ("alert-bell", "after-select-window"):
        unset_hook(inner, hook_name)
    script_path = HOOKS_DIR / f"notify-sidebar-{session}.sh"
    try:
        script_path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Outer session management
# ---------------------------------------------------------------------------

def create_outer_session(session: str) -> None:
    """Create the outer tmux session with sidebar, inner client, and bash pane."""
    inner = inner_session_name(session)
    bash = bash_session_name(session)
    outer = outer_session_name(session)

    if tmux_session_exists(outer) or not tmux_session_exists(inner):
        return

    python_exe = sys.executable or "python3"
    sidebar_cmd = (
        f"TERM=tmux-256color COLORTERM=truecolor {python_exe} -m ccmux.ui.sidebar {session} ; "
        f"echo 'Sidebar exited. Press enter to close.' ; read"
    )

    try:
        create_session_simple(outer, sidebar_cmd)
        if tmux_session_exists(bash):
            split_window(f"{outer}:0.0", "-v", str(BASH_PANE_HEIGHT),
                         f"TMUX= tmux attach -t ={bash}")
        split_window(f"{outer}:0.0", "-h", "50%",
                     f"TMUX= tmux attach -t ={inner}")
        apply_server_global_config()
        apply_outer_session_config(outer)
        install_inner_hook(session)
    except Exception as exc:
        print(
            f"ccmux: failed to create outer session '{outer}': {exc}",
            file=sys.stderr,
        )


def ensure_outer_session(session: str) -> None:
    """Ensure the outer session exists; create if missing."""
    inner = inner_session_name(session)
    if not tmux_session_exists(inner):
        return
    if tmux_session_exists(outer_session_name(session)):
        install_inner_hook(session)
        return
    create_outer_session(session)


def kill_outer_session(session: str) -> bool:
    """Kill the outer tmux session and its associated bash session."""
    bash = bash_session_name(session)
    kill_tmux_session(bash)
    return kill_tmux_session(outer_session_name(session))


# ---------------------------------------------------------------------------
# Bash window management
# ---------------------------------------------------------------------------

def create_bash_window(session: str, instance_name: str, working_dir: str) -> None:
    """Create a window in the bash session for an instance."""
    bash = bash_session_name(session)
    bash_cmd = (
        f"export CCMUX_INSTANCE={instance_name}; "
        f"export COLORTERM=truecolor; "
        f"while true; do $SHELL; done"
    )
    try:
        if not tmux_session_exists(bash):
            _create_bash_session(bash, instance_name, working_dir, bash_cmd)
        else:
            if instance_name in get_tmux_windows(bash):
                return
            create_tmux_window(bash, instance_name, working_dir, bash_cmd)
        set_window_option(f"{bash}:{instance_name}", "window-style", "bg=#1e1e1e")
    except Exception:
        pass


def _create_bash_session(bash: str, instance_name: str, working_dir: str, bash_cmd: str) -> None:
    """Create a new bash tmux session with status off and mouse on."""
    create_tmux_session(bash, instance_name, working_dir, bash_cmd)
    set_session_option(bash, "status", "off")
    set_session_option(bash, "mouse", "on")


# ---------------------------------------------------------------------------
# Debug sidebar
# ---------------------------------------------------------------------------

def do_debug_sidebar() -> None:
    """Launch a debug session to isolate sidebar rendering issues."""
    session_name = "ccmux-debug"
    python_exe = sys.executable or "python3"

    if tmux_session_exists(session_name):
        kill_tmux_session(session_name)

    sidebar_cmd = (
        f"COLORTERM=truecolor "
        f"{python_exe} -m ccmux.ui.sidebar --demo ; "
        f"echo 'Sidebar exited. Press enter to close.' ; read"
    )

    try:
        create_session_simple(session_name, sidebar_cmd)
        split_window(f"{session_name}:0.0", "-v", str(BASH_PANE_HEIGHT), "bash")
        split_window(f"{session_name}:0.0", "-h", "50%", "bash")
        apply_outer_session_config(session_name)
        select_pane(f"{session_name}:0.1")
    except Exception as exc:
        console.print(
            f"[red]Error:[/red] Failed to create debug session: {exc}",
            style="bold",
        )
        sys.exit(1)

    os.execvp("tmux", ["tmux", "attach", "-t", f"={session_name}"])
