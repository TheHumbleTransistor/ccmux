"""Session lifecycle logic for ccmux: create, activate, deactivate, remove, rename.

Functions in this module should raise exceptions for error conditions rather
than calling console.print()/sys.exit() directly. The CLI layer (cli.py)
is responsible for catching exceptions and presenting errors to the user.
"""

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from rich.prompt import Confirm, Prompt

from ccmux import __version__, state
from ccmux.config import run_post_create
from ccmux.display import console, display_session_table, show_session_info
from ccmux.exceptions import (
    ActivationError,
    AttachError,
    DefaultBranchError,
    DetachError,
    InvalidArgumentError,
    NoSessionsFound,
    NotInCcmuxSessionError,
    NotInGitRepoError,
    SessionExistsError,
    SessionNotFoundError,
    TmuxError,
    UserAbortedError,
    WorktreeError,
)
from ccmux.git_ops import (
    check_for_common_default_branches,
    create_worktree,
    get_default_branch,
    get_most_recently_used_branch,
    get_repo_root,
    move_worktree,
    remove_worktree,
    worktree_exists,
    worktree_status,
)
from ccmux.naming import (
    BASH_SESSION,
    INNER_SESSION,
    OUTER_SESSION,
    WORKTREES_DIR_NAME,
    detect_current_ccmux_session,
    detect_current_ccmux_session_any,
    generate_animal_name,
    is_session_window_active,
    sanitize_name,
)
from ccmux.session_layout import (
    create_bash_window,
    create_outer_session,
    ensure_outer_session,
    install_inner_hook,
    kill_outer_session,
    notify_sidebars,
    uninstall_inner_hook,
)
from ccmux.tmux_ops import (
    create_tmux_session,
    create_tmux_window,
    detach_client,
    get_current_tmux_session,
    get_current_tmux_window,
    get_session_id,
    get_tmux_windows,
    kill_all_ccmux_sessions,
    kill_tmux_session,
    kill_tmux_window,
    list_clients,
    rename_tmux_window,
    select_window,
    set_window_user_option,
    tmux_session_exists,
)
from ccmux.ui.tmux import apply_claude_inner_session_config, apply_server_global_config


def _major_minor(version: str) -> str:
    """Extract 'major.minor' from a version string (e.g. '0.3.1.dev5+gabc' → '0.3')."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def stale_sessions_running() -> bool:
    """Return True if the workspace is running on an outdated major.minor version."""
    if not tmux_session_exists(INNER_SESSION):
        return False
    stored = state.get_tmux_session_version()
    if stored is None:
        return True
    return _major_minor(stored) != _major_minor(__version__)


# ---------------------------------------------------------------------------
# Shared helpers (extracted from duplicated patterns)
# ---------------------------------------------------------------------------

def build_claude_command(name: str, path: str, claude_session_id: str, resume: bool = False) -> str:
    """Build the shell command to launch or resume Claude Code in a tmux pane."""
    if resume:
        claude_part = f"claude --resume {claude_session_id} || claude"
    else:
        claude_part = f"claude --session-id {claude_session_id}"
    return (
        f"export CCMUX_SESSION={name}; "
        f"unset CLAUDECODE; "
        f"{claude_part}; while true; do $SHELL; done"
    )


def create_session_window(
    name: str, path: str, launch_cmd: str, is_first: bool,
) -> tuple[Optional[str], Optional[str]]:
    """Create a tmux window for a session, creating the tmux session if first.

    Returns (cc_window_id, bash_window_id).
    """
    if is_first:
        cc_window_id = create_tmux_session(INNER_SESSION, name, path, launch_cmd)
        bash_window_id = None
        if cc_window_id:
            apply_server_global_config()
            bash_window_id = create_bash_window(name, path)
            if apply_claude_inner_session_config(INNER_SESSION):
                console.print(f"  [green]\u2713[/green] Applied workspace configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply workspace configuration (session will use defaults)")
        return cc_window_id, bash_window_id
    else:
        cc_window_id = create_tmux_window(INNER_SESSION, name, path, launch_cmd)
        bash_window_id = None
        if cc_window_id:
            bash_window_id = create_bash_window(name, path)
        return cc_window_id, bash_window_id


def tag_window_with_session_id(window_id: Optional[str], session_name: str) -> None:
    """Tag a tmux window with @ccmux_sid = session's stable integer ID."""
    if not window_id:
        return
    sess = state.get_session(session_name)
    if sess:
        set_window_user_option(window_id, "ccmux_sid", str(sess.id))


def update_session_tmux_state(
    name: str, claude_session_id: str,
    cc_window_id: Optional[str] = None,
    bash_window_id: Optional[str] = None,
) -> None:
    """Update tmux IDs and claude_session_id in state, then tag both windows."""
    session_id = get_session_id(INNER_SESSION)
    if session_id and cc_window_id:
        state.update_tmux_ids(name, session_id, cc_window_id, bash_window_id)
    state.update_session(name, claude_session_id=claude_session_id)
    tag_window_with_session_id(cc_window_id, name)
    tag_window_with_session_id(bash_window_id, name)


def kill_session_windows(
    name: str,
    tmux_cc_window_id: Optional[str],
    tmux_bash_window_id: Optional[str] = None,
) -> bool:
    """Kill a session's inner window and bash window. Returns True if inner killed."""
    killed = False
    if tmux_cc_window_id:
        killed = kill_tmux_window(tmux_cc_window_id)
    if tmux_bash_window_id:
        kill_tmux_window(tmux_bash_window_id)
    else:
        kill_tmux_window(f"{BASH_SESSION}:{name}")
    return killed


def partition_sessions_by_active(sessions: list) -> tuple[list, list]:
    """Split sessions into (active, inactive) lists."""
    active, inactive = [], []
    for sess in sessions:
        if is_session_window_active(sess.tmux_cc_window_id):
            active.append(sess)
        else:
            inactive.append(sess)
    return active, inactive


def find_session_by_name(sessions: list, name: str):
    """Find a session by name in a list. Returns session or None."""
    for sess in sessions:
        if sess.name == name:
            return sess
    return None


def auto_attach_if_outside_tmux(yes: bool = False) -> None:
    """Prompt and attach to tmux if not already inside tmux."""
    if "TMUX" not in os.environ:
        console.print()
        if yes or Confirm.ask("Attach to workspace now?", default=True):
            os.execvp("tmux", ["tmux", "attach", "-t", f"={OUTER_SESSION}"])


def claude_project_dir(session_path: str) -> Path:
    """Compute the Claude Code project directory for a given session path."""
    encoded = re.sub(r'[^a-zA-Z0-9]', '-', session_path)
    return Path.home() / ".claude" / "projects" / encoded


def migrate_claude_session(old_path: str, new_path: str, session_id: str) -> bool:
    """Copy Claude Code session data from old project dir to new.

    Returns True if anything was copied.
    """
    old_dir = claude_project_dir(old_path)
    new_dir = claude_project_dir(new_path)
    if not old_dir.exists():
        return False

    copied = False
    new_dir.mkdir(parents=True, exist_ok=True)

    jsonl_file = old_dir / f"{session_id}.jsonl"
    if jsonl_file.exists():
        shutil.copy2(str(jsonl_file), str(new_dir / f"{session_id}.jsonl"))
        copied = True

    session_subdir = old_dir / session_id
    if session_subdir.is_dir():
        dest_subdir = new_dir / session_id
        if dest_subdir.exists():
            shutil.rmtree(str(dest_subdir))
        shutil.copytree(str(session_subdir), str(dest_subdir))
        copied = True
    return copied


# ---------------------------------------------------------------------------
# session_new decomposed
# ---------------------------------------------------------------------------

def _validate_repo_context(path: Optional[str] = None) -> tuple[Path, str, Path]:
    """Validate git repo and return (repo_root, default_branch, working_dir).

    When *path* is given, *working_dir* is the resolved path (which may be a
    subdirectory inside the repo).  Otherwise *working_dir* equals *repo_root*.
    """
    if path is not None:
        resolved = Path(path).resolve()
        if not resolved.is_dir():
            raise InvalidArgumentError(f"Path is not a directory: {resolved}")
        os.chdir(resolved)
    repo_root = get_repo_root()
    if repo_root is None:
        raise NotInGitRepoError(path or "")
    os.chdir(repo_root)

    default_branch = (
        get_default_branch()
        or check_for_common_default_branches()
        or get_most_recently_used_branch()
    )
    if default_branch is None:
        raise DefaultBranchError()

    working_dir = resolved if path is not None else repo_root
    return repo_root, default_branch, working_dir


def _resolve_session_type(repo_root: Path, worktree: bool, yes: bool) -> bool:
    """Decide whether to create as worktree. Returns create_as_worktree flag."""
    if worktree:
        return True
    existing_main = state.find_main_repo_session(str(repo_root))
    if existing_main:
        console.print(f"[yellow]Warning:[/yellow] Main repository already has a session: '{existing_main.name}'")
        if yes or Confirm.ask("Create a worktree instead?", default=True):
            return True
        raise UserAbortedError("Main repository already in use.")
    return False


def session_name_exists(name: str, repo_root: Path) -> bool:
    """Check if a session name is already in use (session state or worktree on disk)."""
    if state.get_session(name):
        return True
    test_path = repo_root / WORKTREES_DIR_NAME / name
    return worktree_exists(test_path, repo_root)


def _generate_session_name(repo_root: Path, create_as_worktree: bool, name: Optional[str]) -> str:
    """Generate or sanitize session name."""
    if name is not None:
        sanitized = sanitize_name(name)
        if session_name_exists(sanitized, repo_root):
            raise SessionExistsError(sanitized)
        return sanitized

    for _ in range(20):
        candidate = sanitize_name(generate_animal_name())
        if not session_name_exists(candidate, repo_root):
            return candidate

    base = sanitize_name(generate_animal_name())
    suffix = __import__("random").randint(10, 99)
    return f"{base}-{suffix}"


def _setup_worktree(repo_root: Path, session_path: Path, default_branch: str, name: str) -> None:
    """Create the git worktree and run post_create hooks."""
    if worktree_exists(session_path, repo_root):
        console.print("  [yellow]Worktree already exists, reusing it.[/yellow]")
    else:
        try:
            create_worktree(repo_root, session_path, default_branch)
            console.print(f"  [green]\u2713[/green] Created detached worktree from {default_branch}")
        except subprocess.CalledProcessError as e:
            raise WorktreeError("creation", str(e)) from e
    run_post_create(repo_root, session_path, name)


def _reactivate_orphaned_sessions(current_name: str) -> None:
    """Reactivate all orphaned sessions when a new tmux session was just created."""
    existing = state.get_all_sessions()
    orphans = [sess for sess in existing if sess.name != current_name]

    if not orphans:
        return

    console.print(f"\n[bold cyan]Reactivating {len(orphans)} orphaned session(s):[/bold cyan]")
    for sess in orphans:
        _reactivate_single_orphan(sess)

    select_window(INNER_SESSION, current_name)


def _reactivate_single_orphan(sess) -> None:
    """Reactivate a single orphaned session."""
    name = sess.name
    path = sess.session_path
    sess_type = sess.session_type + " repo" if not sess.is_worktree else "worktree"

    orphan_session_id = sess.claude_session_id or str(uuid.uuid4())
    cmd = build_claude_command(name, path, orphan_session_id, resume=bool(sess.claude_session_id))

    cc_window_id = create_tmux_window(INNER_SESSION, name, path, cmd)
    if cc_window_id:
        bash_window_id = create_bash_window(name, path)
        update_session_tmux_state(name, orphan_session_id, cc_window_id, bash_window_id)
        console.print(f"  [green]\u2713[/green] Reactivated '{name}'")
    else:
        console.print(f"  [yellow]\u26a0[/yellow] Could not reactivate '{name}'")


def do_session_new(name: Optional[str] = None, worktree: bool = False, yes: bool = False, path: Optional[str] = None) -> None:
    """Create a new Claude Code session."""
    repo_root, default_branch, working_dir = _validate_repo_context(path)
    create_as_worktree = _resolve_session_type(repo_root, worktree, yes)
    name = _generate_session_name(repo_root, create_as_worktree, name)

    if create_as_worktree:
        session_path = repo_root / WORKTREES_DIR_NAME / name
        (repo_root / WORKTREES_DIR_NAME).mkdir(parents=True, exist_ok=True)
    else:
        session_path = working_dir

    _print_creation_info(name, repo_root, create_as_worktree, session_path, default_branch)

    if create_as_worktree:
        _setup_worktree(repo_root, session_path, default_branch, name)

    is_first = not tmux_session_exists(INNER_SESSION)

    session_type = "worktree" if create_as_worktree else "main repo"
    claude_session_id = str(uuid.uuid4())
    launch_cmd = build_claude_command(name, str(session_path), claude_session_id)

    cc_window_id, bash_window_id = _create_new_session_window(name, str(session_path), launch_cmd, is_first)

    _save_new_session_state(name, repo_root, session_path, create_as_worktree, claude_session_id, cc_window_id, bash_window_id)

    notify_sidebars()
    if is_first:
        _reactivate_orphaned_sessions(name)

    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")
    auto_attach_if_outside_tmux(yes)


def _print_creation_info(name: str, repo_root: Path, create_as_worktree: bool, session_path: Path, default_branch: str) -> None:
    """Print session creation information."""
    console.print(f"\n[bold cyan]Creating Claude Code session:[/bold cyan] {name}")
    console.print(f"  Repo root: {repo_root}")
    if create_as_worktree:
        console.print(f"  Type:      Worktree")
        console.print(f"  Path:      {session_path}")
        console.print(f"  Based on:  {default_branch} (detached)")
    else:
        console.print(f"  Type:      Main repository")
        console.print(f"  Path:      {session_path}")


def _create_new_session_window(name: str, path: str, launch_cmd: str, is_first: bool) -> tuple[Optional[str], Optional[str]]:
    """Create the tmux window for a new session. Returns (cc_window_id, bash_window_id)."""
    if is_first:
        cc_window_id = create_tmux_session(INNER_SESSION, name, path, launch_cmd)
        if cc_window_id is None:
            raise TmuxError("session creation")
        apply_server_global_config()
        bash_window_id = create_bash_window(name, path)
        console.print(f"  [green]\u2713[/green] Created workspace with session '{name}'")
        if apply_claude_inner_session_config(INNER_SESSION):
            console.print(f"  [green]\u2713[/green] Applied workspace configuration")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Could not apply workspace configuration (session will use defaults)")
        create_outer_session()
        state.set_tmux_session_version(__version__)
    else:
        cc_window_id = create_tmux_window(INNER_SESSION, name, path, launch_cmd)
        if cc_window_id is None:
            raise TmuxError("window creation")
        bash_window_id = create_bash_window(name, path)
        select_window(INNER_SESSION, name)
        console.print(f"  [green]\u2713[/green] Created new window '{name}'")

    console.print(f"  [green]\u2713[/green] Launched Claude Code in tmux window '{name}'")
    return cc_window_id, bash_window_id


def _save_new_session_state(
    name: str, repo_root: Path, session_path: Path, is_worktree: bool,
    claude_session_id: str, cc_window_id: Optional[str],
    bash_window_id: Optional[str] = None,
) -> None:
    """Save session state after creation, then tag both windows with @ccmux_sid."""
    tmux_session_id = get_session_id(INNER_SESSION)

    state.add_session(
        session_name=name,
        repo_path=str(repo_root),
        session_path=str(session_path),
        tmux_session_id=tmux_session_id,
        tmux_cc_window_id=cc_window_id,
        tmux_bash_window_id=bash_window_id,
        is_worktree=is_worktree,
        claude_session_id=claude_session_id,
    )
    tag_window_with_session_id(cc_window_id, name)
    tag_window_with_session_id(bash_window_id, name)


# ---------------------------------------------------------------------------
# session_rename decomposed
# ---------------------------------------------------------------------------

def _resolve_rename_args(old: Optional[str], new: Optional[str]) -> tuple[str, str, object]:
    """Handle 3 input modes for rename. Returns (old_name, new_name, session_data)."""
    if old is not None and new is not None:
        old_name = old
        new_name = sanitize_name(new)
        session_data = state.get_session(old_name)
        if not session_data:
            raise SessionNotFoundError(old_name)
    elif old is not None and new is None:
        new_name = sanitize_name(old)
        detected = detect_current_ccmux_session_any()
        if not detected:
            raise NotInCcmuxSessionError()
        old_name = detected[0]
        session_data = detected[1]
    elif old is None and new is None:
        old_name, new_name, session_data = _interactive_rename()
    else:
        raise InvalidArgumentError("Provide both old and new names, one name to rename current session, or run without args for interactive mode.")
    return old_name, new_name, session_data


def _interactive_rename() -> tuple[str, str, object]:
    """Handle interactive rename mode."""
    sessions = state.get_all_sessions()
    if not sessions:
        raise NoSessionsFound()

    console.print(f"\n[bold]Sessions:[/bold]")
    for i, sess in enumerate(sessions):
        console.print(f"  {i + 1}. {sess.name}")

    choice = Prompt.ask(
        "\nSelect session to rename",
        choices=[str(i + 1) for i in range(len(sessions))],
    )
    old_name = sessions[int(choice) - 1].name
    session_data = state.get_session(old_name)
    raw_new = Prompt.ask("New name")
    new_name = sanitize_name(raw_new)
    return old_name, new_name, session_data


def _rename_active_worktree(old_name: str, new_name: str, session_data) -> None:
    """Rename an active worktree session."""
    old_path = Path(session_data.session_path)
    repo_path = Path(session_data.repo_path)
    new_path = old_path.parent / new_name
    tmux_cc_window_id = session_data.tmux_cc_window_id

    console.print(f"\n[bold yellow]Session '{old_name}' is active.[/bold yellow]")
    console.print("Renaming will restart Claude Code with its conversation resumed in the new directory.")
    if not Confirm.ask("Continue?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    if old_path.exists():
        try:
            move_worktree(repo_path, old_path, new_path)
            console.print(f"  [green]\u2713[/green] Moved worktree directory: {old_path.name} -> {new_path.name}")
        except subprocess.CalledProcessError as e:
            raise WorktreeError("move", str(e)) from e

    migrated = _migrate_session_data(session_data, old_path, new_path)

    if not state.rename_session(old_name, new_name):
        if not state.get_session(old_name):
            raise SessionNotFoundError(old_name)
        raise SessionExistsError(new_name)
    state.update_session(new_name, session_path=str(new_path))

    new_cc_window_id = _create_renamed_window(new_name, new_path, session_data, migrated)

    new_bash_window_id = create_bash_window(new_name, str(new_path))

    if new_cc_window_id:
        update_session_tmux_state(new_name,
                                   session_data.claude_session_id if migrated else str(uuid.uuid4()),
                                   new_cc_window_id, new_bash_window_id)

    _kill_old_rename_windows(old_name, tmux_cc_window_id, new_name, new_cc_window_id)


def _migrate_session_data(session_data, old_path: Path, new_path: Path) -> bool:
    """Migrate Claude session data between paths. Returns True if migrated."""
    old_session_id = session_data.claude_session_id
    if old_session_id:
        migrated = migrate_claude_session(str(old_path), str(new_path), old_session_id)
        if migrated:
            console.print(f"  [green]\u2713[/green] Migrated Claude session data")
        return migrated
    return False


def _create_renamed_window(new_name: str, new_path: Path, session_data, migrated: bool) -> Optional[str]:
    """Create a new tmux window for the renamed session."""
    old_session_id = session_data.claude_session_id
    new_session_id = old_session_id if migrated else str(uuid.uuid4())

    launch_cmd = build_claude_command(
        new_name, str(new_path), new_session_id,
        resume=bool(migrated and old_session_id),
    )

    window_id = create_tmux_window(INNER_SESSION, new_name, str(new_path), launch_cmd)
    if window_id:
        console.print(f"  [green]\u2713[/green] Created new Claude Code window '{new_name}'")
    else:
        console.print(f"  [red]\u2717[/red] Could not create new Claude Code window")
        console.print(f"  [yellow]Run `ccmux activate {new_name}` to start it manually.[/yellow]")
    return window_id


def _kill_old_rename_windows(old_name: str, old_window_id: Optional[str], new_name: str, new_window_id: Optional[str]) -> None:
    """Kill old windows and clean up after rename."""
    placeholder_created = False
    windows = get_tmux_windows(INNER_SESSION)
    if len(windows) <= 1:
        wid = create_tmux_window(INNER_SESSION, "_ccmux_placeholder", "/tmp", "sleep 60")
        placeholder_created = wid is not None

    if old_window_id:
        if kill_tmux_window(old_window_id):
            console.print(f"  [green]\u2713[/green] Killed old Claude Code window")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Old Claude Code window already gone")

    kill_tmux_window(f"{BASH_SESSION}:{old_name}")

    if placeholder_created:
        kill_tmux_window(f"{INNER_SESSION}:_ccmux_placeholder")
    if new_window_id:
        select_window(INNER_SESSION, new_name)


def _rename_inactive_worktree(old_name: str, new_name: str, session_data) -> None:
    """Rename an inactive worktree session."""
    old_path = Path(session_data.session_path)
    repo_path = Path(session_data.repo_path)
    new_path = old_path.parent / new_name

    if old_path.exists():
        try:
            move_worktree(repo_path, old_path, new_path)
            console.print(f"  [green]\u2713[/green] Moved worktree directory: {old_path.name} -> {new_path.name}")
        except subprocess.CalledProcessError as e:
            raise WorktreeError("move", str(e)) from e

    if not state.rename_session(old_name, new_name):
        if not state.get_session(old_name):
            raise SessionNotFoundError(old_name)
        raise SessionExistsError(new_name)
    state.update_session(new_name, session_path=str(new_path))


def _rename_main_repo_session(old_name: str, new_name: str, session_data, is_active: bool) -> None:
    """Rename a main repo (non-worktree) session."""
    if not state.rename_session(old_name, new_name):
        if not state.get_session(old_name):
            raise SessionNotFoundError(old_name)
        raise SessionExistsError(new_name)

    if is_active:
        tmux_cc_window_id = session_data.tmux_cc_window_id
        if rename_tmux_window(tmux_cc_window_id, new_name):
            console.print(f"  [green]\u2713[/green] Renamed tmux window")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Could not rename tmux window")
        rename_tmux_window(f"{BASH_SESSION}:{old_name}", new_name)



def do_session_rename(old: Optional[str] = None, new: Optional[str] = None) -> None:
    """Rename a session."""
    old_name, new_name, session_data = _resolve_rename_args(old, new)

    if old_name == new_name:
        console.print(f"[yellow]Session is already named '{old_name}'.[/yellow]")
        return

    repo_root = Path(session_data.repo_path)
    if session_name_exists(new_name, repo_root):
        raise SessionExistsError(new_name)

    is_wt = session_data.is_worktree
    tmux_cc_window_id = session_data.tmux_cc_window_id
    is_active = tmux_cc_window_id and is_session_window_active(tmux_cc_window_id)

    if is_wt:
        if is_active:
            _rename_active_worktree(old_name, new_name, session_data)
        else:
            _rename_inactive_worktree(old_name, new_name, session_data)
    else:
        _rename_main_repo_session(old_name, new_name, session_data, is_active)

    notify_sidebars()
    console.print(f"\n[bold green]Success![/bold green] Session renamed: '{old_name}' -> '{new_name}'")


# ---------------------------------------------------------------------------
# session_remove decomposed
# ---------------------------------------------------------------------------

def _delete_session_worktree(session, prefix: str = "  ") -> None:
    """Delete the git worktree for a session with messaging."""
    if not session.is_worktree:
        console.print(f"{prefix}[dim]Main repository - no git worktree to remove[/dim]")
        return

    wt_path = Path(session.session_path)
    repo_path = Path(session.repo_path)
    if worktree_exists(wt_path, repo_path):
        try:
            remove_worktree(repo_path, wt_path)
            console.print(f"{prefix}[green]\u2713[/green] Removed git worktree '{session.name}'")
        except subprocess.CalledProcessError as e:
            console.print(f"{prefix}[yellow]\u26a0[/yellow] Git worktree removal failed: {e}")
            console.print(f"{prefix}  [dim]Will remove from tracking anyway...[/dim]")
    else:
        console.print(f"{prefix}[yellow]\u26a0[/yellow] Worktree not found on filesystem")


def _remove_all_sessions(sessions: list, yes: bool) -> None:
    """Remove all sessions."""
    active, inactive = partition_sessions_by_active(sessions)

    console.print(f"\n[bold red]WARNING: This will permanently delete {len(sessions)} session(s)[/bold red]")
    console.print("[red]Any uncommitted changes will be lost![/red]\n")

    # Gather dirty file info per session for display
    dirty_map: dict[str, list[str]] = {}
    for sess in sessions:
        if sess.is_worktree and Path(sess.session_path).exists():
            dirty = worktree_status(Path(sess.session_path))
            if dirty:
                dirty_map[sess.name] = dirty

    if active:
        console.print(f"  Active ({len(active)}):")
        for sess in active:
            dirty_tag = f" [bold yellow]({len(dirty_map[sess.name])} uncommitted change(s))[/bold yellow]" if sess.name in dirty_map else ""
            console.print(f"    \u2022 {sess.name}{dirty_tag}")
    if inactive:
        console.print(f"  Inactive ({len(inactive)}):")
        for sess in inactive:
            dirty_tag = f" [bold yellow]({len(dirty_map[sess.name])} uncommitted change(s))[/bold yellow]" if sess.name in dirty_map else ""
            console.print(f"    \u2022 {sess.name}{dirty_tag}")
    console.print()

    if not yes:
        if not Confirm.ask(f"[bold red]Permanently remove all {len(sessions)} session(s)?[/bold red]", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Delete worktrees and remove from state BEFORE killing tmux windows.
    # This ensures cleanup completes even if the user is running ccmux
    # from a bash pane of a session being removed.
    removed = 0
    for sess in sessions:
        prefix = "  "
        _delete_session_worktree(sess, prefix)
        state.remove_session(sess.name)
        console.print(f"{prefix}[green]\u2713[/green] Removed '{sess.name}' from tracking")
        removed += 1

    _kill_remove_all_sessions()
    console.print(f"\n[bold green]Success![/bold green] Removed {removed} session(s).")


def _kill_remove_all_sessions() -> None:
    """Kill all tmux sessions after removing all sessions."""
    if kill_tmux_session(OUTER_SESSION):
        console.print(f"\n[green]\u2713[/green] Stopped workspace UI session '{OUTER_SESSION}'")
    if kill_tmux_session(INNER_SESSION):
        console.print(f"[green]\u2713[/green] Stopped workspace inner session '{INNER_SESSION}'")
    if kill_tmux_session(BASH_SESSION):
        console.print(f"[green]\u2713[/green] Stopped workspace bash session '{BASH_SESSION}'")


def _remove_single_session(name: str, sessions: list, yes: bool) -> None:
    """Remove a single session."""
    active, _ = partition_sessions_by_active(sessions)
    session = find_session_by_name(sessions, name)

    if session is None:
        raise SessionNotFoundError(name, "List sessions with: ccmux list")

    is_active = session in active
    is_main_repo = not session.is_worktree
    wt_path = Path(session.session_path)

    # Check for uncommitted changes in worktree sessions
    dirty_files: list[str] = []
    if session.is_worktree and wt_path.exists():
        dirty_files = worktree_status(wt_path)

    _print_remove_warning(name, is_main_repo, wt_path, is_active, dirty_files)

    if not yes:
        if dirty_files:
            # Require typing session name to confirm when there are uncommitted changes
            typed = Prompt.ask(
                f"[bold red]Type the session name '{name}' to confirm removal[/bold red]"
            )
            if typed != name:
                console.print("[yellow]Cancelled \u2014 name did not match.[/yellow]")
                return
        else:
            prompt = f"[bold red]Remove '{name}' from tracking?[/bold red]" if is_main_repo else f"[bold red]Permanently remove session '{name}'?[/bold red]"
            if not Confirm.ask(prompt, default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                return

    # Delete worktree and remove from state BEFORE killing tmux windows.
    # This ensures cleanup completes even if the user is running ccmux
    # from the bash pane of the session being removed (killing that window
    # would terminate this process).
    _delete_session_worktree(session)
    state.remove_session(name)
    console.print(f"  [green]\u2713[/green] Removed '{name}' from tracking")

    if is_active:
        kill_session_windows(name, session.tmux_cc_window_id, session.tmux_bash_window_id)
        console.print(f"  [green]\u2713[/green] Deactivated '{name}'")

    notify_sidebars()

    remaining = state.get_all_sessions()
    if not remaining:
        uninstall_inner_hook()
        kill_outer_session()
        kill_tmux_session(INNER_SESSION)

    if is_main_repo:
        console.print(f"\n[bold green]Success![/bold green] Main repository '{name}' removed from tracking.")
    else:
        console.print(f"\n[bold green]Success![/bold green] Session '{name}' removed.")


def _print_remove_warning(
    name: str, is_main_repo: bool, wt_path: Path, is_active: bool,
    dirty_files: list[str] | None = None,
) -> None:
    """Print the warning message before removing a session."""
    if is_main_repo:
        console.print(f"\n[bold red]WARNING: Removing main repository '{name}' from tracking[/bold red]")
        console.print("[yellow]This will only remove it from ccmux tracking, not delete the repository itself.[/yellow]")
    else:
        console.print(f"\n[bold red]WARNING: Removing session '{name}'[/bold red]")
        console.print("[red]This will permanently delete the worktree and any uncommitted changes![/red]")
    console.print(f"  Path: {wt_path}")
    console.print(f"  Status: {'Active' if is_active else 'Inactive'}")

    if dirty_files:
        console.print()
        console.print(f"  [bold yellow]\u26a0 UNCOMMITTED CHANGES ({len(dirty_files)} file(s)):[/bold yellow]")
        for f in dirty_files[:20]:
            console.print(f"    [yellow]{f}[/yellow]")
        if len(dirty_files) > 20:
            console.print(f"    [dim]... and {len(dirty_files) - 20} more[/dim]")

    console.print()


def do_session_remove(name: Optional[str] = None, yes: bool = False, all_sessions: bool = False) -> None:
    """Remove session(s) permanently."""
    if name is None and not all_sessions:
        detected = detect_current_ccmux_session_any()
        if detected:
            name = detected[0]
        else:
            raise InvalidArgumentError(
                "No session name provided and could not auto-detect.\n"
                "  Run from within a workspace session, or specify a name:\n"
                "    ccmux remove <name>\n"
                "  To remove all sessions:\n"
                "    ccmux remove --all"
            )

    sessions = state.get_all_sessions()
    if not sessions:
        raise NoSessionsFound()

    if name is None:
        _remove_all_sessions(sessions, yes)
    else:
        _remove_single_session(name, sessions, yes)


# ---------------------------------------------------------------------------
# session_deactivate decomposed
# ---------------------------------------------------------------------------

def _deactivate_all_sessions(active_sessions: list, yes: bool) -> None:
    """Deactivate all active sessions."""
    if not active_sessions:
        console.print(f"\n[yellow]No active sessions to deactivate.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating {len(active_sessions)} active session(s):[/bold yellow]")
    for sess in active_sessions:
        console.print(f"  \u2022 {sess.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"Deactivate all {len(active_sessions)} session(s)?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    deactivated = 0
    for sess in active_sessions:
        if kill_session_windows(sess.name, sess.tmux_cc_window_id, sess.tmux_bash_window_id):
            console.print(f"  [green]\u2713[/green] Deactivated '{sess.name}'")
            deactivated += 1
        else:
            console.print(f"  [yellow]Window '{sess.name}' not found or already closed[/yellow]")
            # Still kill the bash window
            kill_tmux_window(f"{BASH_SESSION}:{sess.name}")
        state.clear_tmux_window_ids(sess.name)

    notify_sidebars()
    console.print(f"\n[bold green]Success![/bold green] Deactivated {deactivated} session(s).")


def _deactivate_single_session(name: str, sessions: list, active_sessions: list) -> None:
    """Deactivate a single session."""
    session = find_session_by_name(sessions, name)
    if session is None:
        raise SessionNotFoundError(name)

    if session not in active_sessions:
        console.print(f"[yellow]Session '{name}' is already inactive.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating session '{name}'[/bold yellow]")

    if kill_session_windows(name, session.tmux_cc_window_id, session.tmux_bash_window_id):
        console.print(f"  [green]\u2713[/green] Deactivated '{name}'")
    else:
        console.print(f"  [yellow]Window '{name}' not found or already closed[/yellow]")
    state.clear_tmux_window_ids(name)

    notify_sidebars()
    console.print(f"\n[bold green]Success![/bold green] Session '{name}' deactivated.")


def do_session_deactivate(name: Optional[str] = None, yes: bool = False) -> None:
    """Deactivate Claude Code session(s)."""
    sessions = state.get_all_sessions()

    if not sessions:
        raise NoSessionsFound()

    active, _ = partition_sessions_by_active(sessions)

    if name is None:
        detected = detect_current_ccmux_session_any()
        if detected:
            name = detected[0]

    if name is None:
        _deactivate_all_sessions(active, yes)
    else:
        _deactivate_single_session(name, sessions, active)


# ---------------------------------------------------------------------------
# activate decomposed
# ---------------------------------------------------------------------------

def _activate_all(yes: bool = False) -> None:
    """Activate all inactive sessions."""
    sessions = state.get_all_sessions()
    if not sessions:
        raise NoSessionsFound("Create one with: ccmux new")

    _, inactive = partition_sessions_by_active(sessions)
    if not inactive:
        ensure_outer_session()
        console.print("\n[yellow]No inactive sessions to activate.[/yellow]")
        return

    console.print(f"\n[bold cyan]Found {len(inactive)} inactive session(s):[/bold cyan]")
    for sess in inactive:
        console.print(f"  \u2022 {sess.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"Activate all {len(inactive)} session(s)?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    inner_exists = tmux_session_exists(INNER_SESSION)
    activated = 0

    for i, sess in enumerate(inactive):
        if sess.tmux_cc_window_id:
            state.clear_tmux_window_ids(sess.name)
        is_first = not inner_exists and i == 0
        claude_session_id = sess.claude_session_id or str(uuid.uuid4())
        launch_cmd = build_claude_command(sess.name, sess.session_path, claude_session_id, resume=bool(sess.claude_session_id))

        cc_window_id, bash_window_id = create_session_window(sess.name, sess.session_path, launch_cmd, is_first)
        if cc_window_id:
            if is_first:
                inner_exists = True
                console.print(f"  [green]\u2713[/green] Created workspace and activated '{sess.name}'")
            else:
                console.print(f"  [green]\u2713[/green] Activated '{sess.name}'")
            update_session_tmux_state(sess.name, claude_session_id, cc_window_id, bash_window_id)
            activated += 1
        else:
            console.print(f"  [red]Error activating '{sess.name}'[/red]")

    ensure_outer_session()
    notify_sidebars()
    console.print(f"\n[bold green]Success![/bold green] Activated {activated} session(s).")


def _activate_single(name: str, yes: bool = False) -> None:
    """Activate a single session by name."""
    sessions = state.get_all_sessions()
    if not sessions:
        raise NoSessionsFound("Create one with: ccmux new")

    session = find_session_by_name(sessions, name)
    if session is None:
        raise SessionNotFoundError(name, "List sessions with: ccmux list")

    if is_session_window_active(session.tmux_cc_window_id):
        ensure_outer_session()
        console.print(f"[yellow]Session '{name}' is already active.[/yellow]")
        return

    if session.tmux_cc_window_id:
        state.clear_tmux_window_ids(name)

    console.print(f"\n[bold cyan]Activating Claude Code session:[/bold cyan] {name}")
    console.print(f"  Session: {session.session_path}")

    is_first = not tmux_session_exists(INNER_SESSION)
    claude_session_id = session.claude_session_id or str(uuid.uuid4())
    launch_cmd = build_claude_command(name, session.session_path, claude_session_id, resume=bool(session.claude_session_id))

    cc_window_id, bash_window_id = create_session_window(name, session.session_path, launch_cmd, is_first)

    if cc_window_id is None:
        raise ActivationError(name)

    if is_first:
        console.print(f"  [green]\u2713[/green] Created workspace and activated '{name}'")
    else:
        select_window(INNER_SESSION, name)
        console.print(f"  [green]\u2713[/green] Activated '{name}'")

    update_session_tmux_state(name, claude_session_id, cc_window_id, bash_window_id)

    ensure_outer_session()
    notify_sidebars()
    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")
    auto_attach_if_outside_tmux(yes)


def do_session_activate(name: Optional[str] = None, yes: bool = False) -> None:
    """Activate Claude Code in a session."""
    if name is None:
        _activate_all(yes)
    else:
        _activate_single(name, yes)


# ---------------------------------------------------------------------------
# session_kill
# ---------------------------------------------------------------------------

def do_session_kill(yes: bool = False) -> None:
    """Deactivate all sessions and shut down the workspace."""
    sessions = state.get_all_sessions()

    active = [
        sess for sess in sessions
        if is_session_window_active(sess.tmux_cc_window_id)
    ]

    if not active and not tmux_session_exists(OUTER_SESSION):
        console.print("[yellow]No active workspace to shut down.[/yellow]")
        return

    if active:
        console.print(f"\n[bold red]Shutting down workspace with {len(active)} active session(s):[/bold red]")
        for sess in active:
            console.print(f"  \u2022 {sess.name}")
    else:
        console.print("\n[bold red]Shutting down workspace (no active sessions)[/bold red]")

    if not yes:
        if not Confirm.ask("Shut down the workspace?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    kill_all_ccmux_sessions(OUTER_SESSION, OUTER_SESSION, INNER_SESSION, BASH_SESSION)
    console.print("\n[bold green]Workspace shut down.[/bold green]")


# ---------------------------------------------------------------------------
# session_info (default command logic)
# ---------------------------------------------------------------------------

def do_session_info() -> None:
    """Show current session info, or auto-attach/create."""
    detected = _detect_from_env_or_bash()

    if detected:
        session_name, session_data = detected
        show_session_info(session_name, session_data)
        return

    cwd_match = _try_cwd_match()
    if cwd_match:
        return

    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[yellow]Not in a workspace session or git repository.[/yellow]\n")
        return None  # signal to cli.py to print help

    do_session_new(yes=True)


def _detect_from_env_or_bash() -> Optional[tuple]:
    """Try env var and bash-session detection (not cwd fallback)."""
    detected = detect_current_ccmux_session()
    if detected:
        return detected

    tmux_session = get_current_tmux_session()
    if tmux_session and tmux_session == BASH_SESSION:
        window_name = get_current_tmux_window()
        if window_name:
            session_data = state.get_session(window_name)
            if session_data:
                return (window_name, session_data)
    return None


def _try_cwd_match() -> bool:
    """Try matching cwd to a session. Returns True if handled."""
    cwd = str(Path.cwd())
    found = state.find_session_by_path(cwd)
    if not found:
        return False

    session_name, session_data = found
    is_active = (
        session_data.tmux_cc_window_id
        and tmux_session_exists(INNER_SESSION)
        and is_session_window_active(session_data.tmux_cc_window_id)
    )

    if not is_active:
        console.print(f"Found session [cyan]'{session_name}'[/cyan]. Activating...")
        _activate_single(session_name, yes=True)
        return True

    console.print(f"Session [cyan]'{session_name}'[/cyan] is active. Attaching...")
    ensure_outer_session()
    notify_sidebars()
    if "TMUX" not in os.environ:
        os.execvp("tmux", ["tmux", "attach", "-t", f"={OUTER_SESSION}"])
    else:
        console.print(f"Already in tmux. Run: [cyan]tmux attach -t ={OUTER_SESSION}[/cyan]")
    return True


# ---------------------------------------------------------------------------
# Other commands
# ---------------------------------------------------------------------------

def do_detach(all_clients: bool = False) -> None:
    """Detach from the workspace."""
    if not tmux_session_exists(OUTER_SESSION):
        raise DetachError("No active workspace to detach from.")
    try:
        if all_clients:
            detach_client(session=OUTER_SESSION)
        else:
            clients = list_clients(OUTER_SESSION)
            if not clients:
                raise DetachError("No clients attached to the workspace.")
            detach_client(client_tty=clients[0])
    except subprocess.CalledProcessError as e:
        raise DetachError(f"Detach failed: {e}") from e


def do_attach() -> None:
    """Attach to the workspace."""
    sessions = state.get_all_sessions()
    if not sessions:
        raise AttachError("No workspace found.", "Create a session with: ccmux new")

    if not tmux_session_exists(INNER_SESSION):
        raise AttachError("Workspace is not running.", "Activate sessions with: ccmux activate")

    ensure_outer_session()
    notify_sidebars()
    os.execvp("tmux", ["tmux", "attach", "-t", f"={OUTER_SESSION}"])


def do_session_which() -> None:
    """Print the current session name (useful for scripting)."""
    detected = detect_current_ccmux_session_any()
    if detected is None:
        raise NotInCcmuxSessionError()
    print(detected[0])


def do_session_list() -> None:
    """List all sessions in the workspace."""
    sessions = state.get_all_sessions()
    if not sessions:
        console.print("\n[yellow]No sessions found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        return
    display_session_table()
