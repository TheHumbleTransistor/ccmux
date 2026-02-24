"""Instance lifecycle logic for ccmux: create, activate, deactivate, remove, rename."""

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from rich.prompt import Confirm, Prompt

from ccmux import state
from ccmux.config import run_post_create
from ccmux.display import console, display_session_table, show_instance_info
from ccmux.git_ops import (
    create_worktree,
    get_default_branch,
    get_repo_root,
    move_worktree,
    remove_worktree,
    worktree_exists,
)
from ccmux.session_naming import (
    DEFAULT_SESSION,
    bash_session_name,
    ccmux_session_from_tmux,
    detect_current_ccmux_instance,
    detect_current_ccmux_instance_any,
    generate_animal_name,
    inner_session_name,
    is_instance_window_active,
    outer_session_name,
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
    tmux_session_exists,
)
from ccmux.ui.tmux import apply_claude_inner_session_config


# ---------------------------------------------------------------------------
# Shared helpers (extracted from duplicated patterns)
# ---------------------------------------------------------------------------

def build_launch_command(name: str, path: str, claude_session_id: str, description: str = "") -> str:
    """Build the shell command to launch Claude Code in a tmux pane."""
    desc = f" ({description})" if description else ""
    return (
        f"export CCMUX_INSTANCE={name}; "
        f"echo 'Launching Claude Code in {path}{desc}'; "
        f"unset CLAUDECODE; "
        f"claude --session-id {claude_session_id}; while true; do $SHELL; done"
    )


def build_activate_command(name: str, path: str, claude_session_id: str) -> str:
    """Build the shell command to activate Claude Code in a tmux pane."""
    return (
        f"export CCMUX_INSTANCE={name}; "
        f"echo 'Activating Claude Code in {path}'; "
        f"unset CLAUDECODE; "
        f"claude --session-id {claude_session_id}; while true; do $SHELL; done"
    )


def create_instance_window(
    session: str, name: str, path: str, launch_cmd: str, is_first: bool,
) -> Optional[str]:
    """Create a tmux window for an instance, creating the session if first.

    Returns the new tmux window ID, or None on failure.
    """
    inner = inner_session_name(session)
    if is_first:
        window_id = create_tmux_session(inner, name, path, launch_cmd)
        if window_id:
            create_bash_window(session, name, path)
            if apply_claude_inner_session_config(inner):
                console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
            else:
                console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
            create_outer_session(session)
        return window_id
    else:
        window_id = create_tmux_window(inner, name, path, launch_cmd)
        if window_id:
            create_bash_window(session, name, path)
        return window_id


def update_instance_tmux_state(
    name: str, session: str, claude_session_id: str, window_id: Optional[str] = None,
) -> None:
    """Update tmux IDs and claude_session_id in state."""
    inner = inner_session_name(session)
    session_id = get_session_id(inner)
    if session_id and window_id:
        state.update_tmux_ids(name, session, session_id, window_id)
    state.update_instance(name, session, claude_session_id=claude_session_id)


def kill_instance_windows(session: str, name: str, tmux_window_id: Optional[str]) -> bool:
    """Kill an instance's inner window and bash window. Returns True if inner killed."""
    killed = False
    if tmux_window_id:
        killed = kill_tmux_window(tmux_window_id)
    bash = bash_session_name(session)
    kill_tmux_window(f"{bash}:{name}")
    return killed


def partition_instances_by_active(session: str, instances: list) -> tuple[list, list]:
    """Split instances into (active, inactive) lists."""
    active, inactive = [], []
    for inst in instances:
        if is_instance_window_active(session, inst.tmux_window_id):
            active.append(inst)
        else:
            inactive.append(inst)
    return active, inactive


def find_instance_by_name(instances: list, name: str):
    """Find an instance by name in a list. Returns instance or None."""
    for inst in instances:
        if inst.name == name:
            return inst
    return None


def auto_attach_if_outside_tmux(session: str, yes: bool = False) -> None:
    """Prompt and attach to tmux if not already inside tmux."""
    if "TMUX" not in os.environ:
        console.print()
        if yes or Confirm.ask("Attach to tmux session now?", default=True):
            outer = outer_session_name(session)
            os.execvp("tmux", ["tmux", "attach", "-t", f"={outer}"])


def claude_project_dir(instance_path: str) -> Path:
    """Compute the Claude Code project directory for a given instance path."""
    encoded = re.sub(r'[^a-zA-Z0-9]', '-', instance_path)
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
# instance_new decomposed
# ---------------------------------------------------------------------------

def _validate_repo_context() -> tuple[Path, str]:
    """Validate git repo and return (repo_root, default_branch). Exits on error."""
    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[red]Error:[/red] Not inside a git repository.", style="bold")
        sys.exit(1)
    os.chdir(repo_root)

    default_branch = get_default_branch()
    if default_branch is None:
        console.print("[red]Error:[/red] Could not detect default branch (main/master).", style="bold")
        sys.exit(1)
    return repo_root, default_branch


def _resolve_instance_type(repo_root: Path, session: str, worktree: bool, yes: bool) -> bool:
    """Decide whether to create as worktree. Returns create_as_worktree flag."""
    if worktree:
        return True
    existing_main = state.find_main_repo_instance(str(repo_root), session)
    if existing_main:
        console.print(f"[yellow]Warning:[/yellow] Main repository already has an instance: '{existing_main.name}'")
        if yes or Confirm.ask("Create a worktree instead?", default=True):
            return True
        console.print("[red]Aborted:[/red] Main repository already in use.")
        sys.exit(1)
    return False


def _generate_instance_name(session: str, repo_root: Path, create_as_worktree: bool, name: Optional[str]) -> str:
    """Generate or sanitize instance name."""
    if name is not None:
        return sanitize_name(name)

    for _ in range(20):
        candidate = sanitize_name(generate_animal_name())
        if create_as_worktree:
            test_path = repo_root / ".worktrees" / candidate
            if not worktree_exists(test_path, repo_root):
                return candidate
        else:
            if not state.get_instance(candidate, session):
                return candidate

    base = sanitize_name(generate_animal_name())
    suffix = __import__("random").randint(10, 99)
    return f"{base}-{suffix}"


def _setup_worktree(repo_root: Path, instance_path: Path, default_branch: str, name: str, session: str) -> None:
    """Create the git worktree and run post_create hooks."""
    if worktree_exists(instance_path, repo_root):
        console.print("  [yellow]Worktree already exists, reusing it.[/yellow]")
    else:
        try:
            create_worktree(repo_root, instance_path, default_branch)
            console.print(f"  [green]\u2713[/green] Created detached worktree from {default_branch}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error creating worktree:[/red] {e}", style="bold")
            sys.exit(1)
    run_post_create(repo_root, instance_path, name, session)


def _reactivate_orphaned_instances(session: str, current_name: str) -> None:
    """Reactivate all orphaned instances when a new session was just created."""
    inner = inner_session_name(session)
    existing = state.get_all_instances(session)
    orphans = [inst for inst in existing if inst.name != current_name]

    if not orphans:
        return

    console.print(f"\n[bold cyan]Reactivating {len(orphans)} orphaned instance(s):[/bold cyan]")
    for inst in orphans:
        _reactivate_single_orphan(session, inner, inst)

    select_window(inner, current_name)


def _reactivate_single_orphan(session: str, inner: str, inst) -> None:
    """Reactivate a single orphaned instance."""
    inst_name = inst.name
    inst_path = inst.instance_path
    inst_type = inst.instance_type + " repo" if not inst.is_worktree else "worktree"

    orphan_session_id = str(uuid.uuid4())
    cmd = build_launch_command(inst_name, inst_path, orphan_session_id, f"{inst_type} instance: {inst_name}")

    window_id = create_tmux_window(inner, inst_name, inst_path, cmd)
    if window_id:
        create_bash_window(session, inst_name, inst_path)
        update_instance_tmux_state(inst_name, session, orphan_session_id, window_id)
        console.print(f"  [green]\u2713[/green] Reactivated '{inst_name}'")
    else:
        console.print(f"  [yellow]\u26a0[/yellow] Could not reactivate '{inst_name}'")


def do_instance_new(name: Optional[str] = None, worktree: bool = False, yes: bool = False) -> None:
    """Create a new Claude Code instance."""
    session = DEFAULT_SESSION
    repo_root, default_branch = _validate_repo_context()
    create_as_worktree = _resolve_instance_type(repo_root, session, worktree, yes)
    name = _generate_instance_name(session, repo_root, create_as_worktree, name)

    if create_as_worktree:
        instance_path = repo_root / ".worktrees" / name
        (repo_root / ".worktrees").mkdir(exist_ok=True)
    else:
        instance_path = repo_root

    _print_creation_info(name, repo_root, create_as_worktree, instance_path, default_branch)

    if create_as_worktree:
        _setup_worktree(repo_root, instance_path, default_branch, name, session)

    inner = inner_session_name(session)
    is_first = not tmux_session_exists(inner)

    instance_type = "worktree" if create_as_worktree else "main repo"
    claude_session_id = str(uuid.uuid4())
    launch_cmd = build_launch_command(name, str(instance_path), claude_session_id, f"{instance_type} instance: {name}")

    window_id = _create_new_instance_window(session, inner, name, str(instance_path), launch_cmd, is_first)

    _save_new_instance_state(session, name, repo_root, instance_path, create_as_worktree, claude_session_id, window_id)

    notify_sidebars(session)
    if is_first:
        _reactivate_orphaned_instances(session, name)

    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")
    auto_attach_if_outside_tmux(session, yes)


def _print_creation_info(name: str, repo_root: Path, create_as_worktree: bool, instance_path: Path, default_branch: str) -> None:
    """Print instance creation information."""
    console.print(f"\n[bold cyan]Creating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Repo root: {repo_root}")
    if create_as_worktree:
        console.print(f"  Type:      Worktree")
        console.print(f"  Path:      {instance_path}")
        console.print(f"  Based on:  {default_branch} (detached)")
    else:
        console.print(f"  Type:      Main repository")
        console.print(f"  Path:      {instance_path}")


def _create_new_instance_window(session: str, inner: str, name: str, path: str, launch_cmd: str, is_first: bool) -> Optional[str]:
    """Create the tmux window for a new instance."""
    if is_first:
        window_id = create_tmux_session(inner, name, path, launch_cmd)
        if window_id is None:
            console.print(f"[red]Error creating tmux session[/red]", style="bold")
            sys.exit(1)
        create_bash_window(session, name, path)
        console.print(f"  [green]\u2713[/green] Created tmux session '{inner}' with window '{name}'")
        if apply_claude_inner_session_config(inner):
            console.print(f"  [green]\u2713[/green] Applied ccmux tmux configuration")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Could not apply tmux configuration (session will use defaults)")
        create_outer_session(session)
    else:
        window_id = create_tmux_window(inner, name, path, launch_cmd)
        if window_id is None:
            console.print(f"[red]Error creating tmux window[/red]", style="bold")
            sys.exit(1)
        create_bash_window(session, name, path)
        select_window(inner, name)
        console.print(f"  [green]\u2713[/green] Created new window '{name}' in session '{session}'")

    console.print(f"  [green]\u2713[/green] Launched Claude Code in tmux window '{name}'")
    return window_id


def _save_new_instance_state(session: str, name: str, repo_root: Path, instance_path: Path, is_worktree: bool, claude_session_id: str, window_id: Optional[str]) -> None:
    """Save instance state after creation."""
    inner = inner_session_name(session)
    tmux_session_id = get_session_id(inner)

    state.add_instance(
        session_name=session,
        instance_name=name,
        repo_path=str(repo_root),
        instance_path=str(instance_path),
        tmux_session_id=tmux_session_id,
        tmux_window_id=window_id,
        is_worktree=is_worktree,
        claude_session_id=claude_session_id,
    )


# ---------------------------------------------------------------------------
# instance_rename decomposed
# ---------------------------------------------------------------------------

def _resolve_rename_args(old: Optional[str], new: Optional[str], session: str) -> tuple[str, str, str, object]:
    """Handle 3 input modes for rename. Returns (session, old_name, new_name, instance_data)."""
    if old is not None and new is not None:
        old_name = old
        new_name = sanitize_name(new)
        instance_data = state.get_instance(old_name, session)
        if not instance_data:
            console.print(f"[red]Error:[/red] Instance '{old_name}' not found.", style="bold")
            sys.exit(1)
    elif old is not None and new is None:
        new_name = sanitize_name(old)
        detected = detect_current_ccmux_instance_any()
        if not detected:
            console.print("[red]Error:[/red] Not in a ccmux instance.", style="bold")
            sys.exit(1)
        session = detected[0]
        old_name = detected[1]
        instance_data = detected[2]
    elif old is None and new is None:
        session, old_name, new_name, instance_data = _interactive_rename(session)
    else:
        console.print("[red]Error:[/red] Provide both old and new names, one name to rename current instance, or run without args for interactive mode.", style="bold")
        sys.exit(1)
    return session, old_name, new_name, instance_data


def _interactive_rename(session: str) -> tuple[str, str, str, object]:
    """Handle interactive rename mode."""
    instances = state.get_all_instances(session)
    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold]Instances:[/bold]")
    for i, inst in enumerate(instances):
        console.print(f"  {i + 1}. {inst.name}")

    choice = Prompt.ask(
        "\nSelect instance to rename",
        choices=[str(i + 1) for i in range(len(instances))],
    )
    old_name = instances[int(choice) - 1].name
    instance_data = state.get_instance(old_name, session)
    raw_new = Prompt.ask("New name")
    new_name = sanitize_name(raw_new)
    return session, old_name, new_name, instance_data


def _rename_active_worktree(session: str, old_name: str, new_name: str, instance_data) -> None:
    """Rename an active worktree instance."""
    old_path = Path(instance_data.instance_path)
    repo_path = Path(instance_data.repo_path)
    new_path = old_path.parent / new_name
    inner = inner_session_name(session)
    bash = bash_session_name(session)
    tmux_window_id = instance_data.tmux_window_id

    console.print(f"\n[bold yellow]Instance '{old_name}' is active.[/bold yellow]")
    console.print("Renaming will restart Claude Code with its conversation resumed in the new directory.")
    if not Confirm.ask("Continue?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    if old_path.exists():
        try:
            move_worktree(repo_path, old_path, new_path)
            console.print(f"  [green]\u2713[/green] Moved worktree directory: {old_path.name} -> {new_path.name}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error moving worktree:[/red] {e}", style="bold")
            sys.exit(1)

    migrated = _migrate_session_data(instance_data, old_path, new_path)

    if not state.rename_instance(old_name, new_name, session):
        _print_rename_error(old_name, new_name, session)
        sys.exit(1)
    state.update_instance(new_name, session, instance_path=str(new_path))

    new_window_id = _create_renamed_window(session, inner, new_name, new_path, instance_data, migrated)

    create_bash_window(session, new_name, str(new_path))

    if new_window_id:
        update_instance_tmux_state(new_name, session,
                                    instance_data.claude_session_id if migrated else str(uuid.uuid4()),
                                    new_window_id)

    _kill_old_rename_windows(inner, bash, old_name, tmux_window_id, new_name, new_window_id)


def _migrate_session_data(instance_data, old_path: Path, new_path: Path) -> bool:
    """Migrate Claude session data between paths. Returns True if migrated."""
    old_session_id = instance_data.claude_session_id
    if old_session_id:
        migrated = migrate_claude_session(str(old_path), str(new_path), old_session_id)
        if migrated:
            console.print(f"  [green]\u2713[/green] Migrated Claude session data")
        return migrated
    return False


def _create_renamed_window(session: str, inner: str, new_name: str, new_path: Path, instance_data, migrated: bool) -> Optional[str]:
    """Create a new tmux window for the renamed instance."""
    old_session_id = instance_data.claude_session_id
    new_session_id = old_session_id if migrated else str(uuid.uuid4())

    if migrated and old_session_id:
        claude_arg = f"claude --resume {old_session_id}"
    else:
        claude_arg = f"claude --session-id {new_session_id}"

    launch_cmd = (
        f"export CCMUX_INSTANCE={new_name}; "
        f"echo 'Launching Claude Code in {new_path}'; "
        f"unset CLAUDECODE; "
        f"{claude_arg}; while true; do $SHELL; done"
    )

    window_id = create_tmux_window(inner, new_name, str(new_path), launch_cmd)
    if window_id:
        console.print(f"  [green]\u2713[/green] Created new Claude Code window '{new_name}'")
    else:
        console.print(f"  [red]\u2717[/red] Could not create new Claude Code window")
        console.print(f"  [yellow]Run `ccmux activate {new_name}` to start it manually.[/yellow]")
    return window_id


def _kill_old_rename_windows(inner: str, bash: str, old_name: str, old_window_id: Optional[str], new_name: str, new_window_id: Optional[str]) -> None:
    """Kill old windows and clean up after rename."""
    placeholder_created = False
    windows = get_tmux_windows(inner)
    if len(windows) <= 1:
        wid = create_tmux_window(inner, "_ccmux_placeholder", "/tmp", "sleep 60")
        placeholder_created = wid is not None

    if old_window_id:
        if kill_tmux_window(old_window_id):
            console.print(f"  [green]\u2713[/green] Killed old Claude Code window")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Old Claude Code window already gone")

    kill_tmux_window(f"{bash}:{old_name}")

    if placeholder_created:
        kill_tmux_window(f"{inner}:_ccmux_placeholder")
    if new_window_id:
        select_window(inner, new_name)


def _rename_inactive_worktree(session: str, old_name: str, new_name: str, instance_data) -> None:
    """Rename an inactive worktree instance."""
    old_path = Path(instance_data.instance_path)
    repo_path = Path(instance_data.repo_path)
    new_path = old_path.parent / new_name

    if old_path.exists():
        try:
            move_worktree(repo_path, old_path, new_path)
            console.print(f"  [green]\u2713[/green] Moved worktree directory: {old_path.name} -> {new_path.name}")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error moving worktree:[/red] {e}", style="bold")
            sys.exit(1)

    if not state.rename_instance(old_name, new_name, session):
        _print_rename_error(old_name, new_name, session)
        sys.exit(1)
    state.update_instance(new_name, session, instance_path=str(new_path))


def _rename_main_repo_instance(session: str, old_name: str, new_name: str, instance_data, is_active: bool) -> None:
    """Rename a main repo (non-worktree) instance."""
    if not state.rename_instance(old_name, new_name, session):
        _print_rename_error(old_name, new_name, session)
        sys.exit(1)

    if is_active:
        tmux_window_id = instance_data.tmux_window_id
        bash = bash_session_name(session)
        if rename_tmux_window(tmux_window_id, new_name):
            console.print(f"  [green]\u2713[/green] Renamed tmux window")
        else:
            console.print(f"  [yellow]\u26a0[/yellow] Could not rename tmux window")
        rename_tmux_window(f"{bash}:{old_name}", new_name)


def _print_rename_error(old_name: str, new_name: str, session: str) -> None:
    """Print rename error message."""
    if not state.get_instance(old_name, session):
        console.print(f"[red]Error:[/red] Instance '{old_name}' not found.", style="bold")
    else:
        console.print(f"[red]Error:[/red] Instance '{new_name}' already exists.", style="bold")


def do_instance_rename(old: Optional[str] = None, new: Optional[str] = None) -> None:
    """Rename a ccmux instance."""
    session = DEFAULT_SESSION
    session, old_name, new_name, instance_data = _resolve_rename_args(old, new, session)

    if old_name == new_name:
        console.print(f"[yellow]Instance is already named '{old_name}'.[/yellow]")
        return

    is_wt = instance_data.is_worktree
    tmux_window_id = instance_data.tmux_window_id
    is_active = tmux_window_id and is_instance_window_active(session, tmux_window_id)

    if is_wt:
        if is_active:
            _rename_active_worktree(session, old_name, new_name, instance_data)
        else:
            _rename_inactive_worktree(session, old_name, new_name, instance_data)
    else:
        _rename_main_repo_instance(session, old_name, new_name, instance_data, is_active)

    notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Instance renamed: '{old_name}' -> '{new_name}'")


# ---------------------------------------------------------------------------
# instance_remove decomposed
# ---------------------------------------------------------------------------

def _delete_instance_worktree(instance, prefix: str = "  ") -> None:
    """Delete the git worktree for an instance with messaging."""
    if not instance.is_worktree:
        console.print(f"{prefix}[dim]Main repository - no git worktree to remove[/dim]")
        return

    wt_path = Path(instance.instance_path)
    repo_path = Path(instance.repo_path)
    if worktree_exists(wt_path, repo_path):
        try:
            remove_worktree(repo_path, wt_path)
            console.print(f"{prefix}[green]\u2713[/green] Removed git worktree '{instance.name}'")
        except subprocess.CalledProcessError as e:
            console.print(f"{prefix}[yellow]\u26a0[/yellow] Git worktree removal failed: {e}")
            console.print(f"{prefix}  [dim]Will remove from tracking anyway...[/dim]")
    else:
        console.print(f"{prefix}[yellow]\u26a0[/yellow] Worktree not found on filesystem")


def _remove_all_instances(session: str, instances: list, yes: bool) -> None:
    """Remove all instances."""
    active, inactive = partition_instances_by_active(session, instances)

    console.print(f"\n[bold red]WARNING: This will permanently delete {len(instances)} instance(s)[/bold red]")
    console.print("[red]Any uncommitted changes will be lost![/red]\n")

    if active:
        console.print(f"  Active ({len(active)}):")
        for wt in active:
            console.print(f"    \u2022 {wt.name}")
    if inactive:
        console.print(f"  Inactive ({len(inactive)}):")
        for wt in inactive:
            console.print(f"    \u2022 {wt.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"[bold red]Permanently remove all {len(instances)} instance(s)?[/bold red]", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    removed = 0
    for wt in instances:
        is_active = wt in active
        if is_active and wt.tmux_window_id:
            if kill_tmux_window(wt.tmux_window_id):
                console.print(f"  [green]\u2713[/green] Deactivated '{wt.name}'")
            else:
                console.print(f"  [yellow]Window '{wt.name}' already closed[/yellow]")

        prefix = "    " if is_active else "  "
        _delete_instance_worktree(wt, prefix)
        state.remove_instance(wt.name, session)
        console.print(f"{prefix}[green]\u2713[/green] Removed '{wt.name}' from tracking")
        removed += 1

    _kill_remove_all_sessions(session)
    console.print(f"\n[bold green]Success![/bold green] Removed {removed} instance(s).")


def _kill_remove_all_sessions(session: str) -> None:
    """Kill all tmux sessions after removing all instances."""
    inner = inner_session_name(session)
    bash = bash_session_name(session)
    outer = outer_session_name(session)

    if kill_tmux_session(outer):
        console.print(f"\n[green]\u2713[/green] Killed outer tmux session '{outer}'")
    if kill_tmux_session(inner):
        console.print(f"[green]\u2713[/green] Killed inner tmux session '{inner}'")
    if kill_tmux_session(bash):
        console.print(f"[green]\u2713[/green] Killed bash tmux session '{bash}'")


def _remove_single_instance(session: str, name: str, instances: list, yes: bool) -> None:
    """Remove a single instance."""
    active, _ = partition_instances_by_active(session, instances)
    worktree = find_instance_by_name(instances, name)

    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list[/cyan]")
        sys.exit(1)

    is_active = worktree in active
    is_main_repo = not worktree.is_worktree
    wt_path = Path(worktree.instance_path)

    _print_remove_warning(name, is_main_repo, wt_path, is_active)

    if not yes:
        prompt = f"[bold red]Remove '{name}' from tracking?[/bold red]" if is_main_repo else f"[bold red]Permanently remove instance '{name}'?[/bold red]"
        if not Confirm.ask(prompt, default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    if is_active:
        kill_instance_windows(session, name, worktree.tmux_window_id)
        console.print(f"  [green]\u2713[/green] Deactivated '{name}'")

    _delete_instance_worktree(worktree)
    state.remove_instance(name, session)
    notify_sidebars(session)
    console.print(f"  [green]\u2713[/green] Removed '{name}' from tracking")

    remaining = state.get_all_instances(session)
    if not remaining:
        uninstall_inner_hook(session)
        kill_outer_session(session)
        inner = inner_session_name(session)
        kill_tmux_session(inner)

    if is_main_repo:
        console.print(f"\n[bold green]Success![/bold green] Main repository '{name}' removed from tracking.")
    else:
        console.print(f"\n[bold green]Success![/bold green] Instance '{name}' removed.")


def _print_remove_warning(name: str, is_main_repo: bool, wt_path: Path, is_active: bool) -> None:
    """Print the warning message before removing an instance."""
    if is_main_repo:
        console.print(f"\n[bold red]WARNING: Removing main repository '{name}' from tracking[/bold red]")
        console.print("[yellow]This will only remove it from ccmux tracking, not delete the repository itself.[/yellow]")
    else:
        console.print(f"\n[bold red]WARNING: Removing instance '{name}'[/bold red]")
        console.print("[red]This will permanently delete the worktree and any uncommitted changes![/red]")
    console.print(f"  Path: {wt_path}")
    console.print(f"  Status: {'Active' if is_active else 'Inactive'}\n")


def do_instance_remove(name: Optional[str] = None, yes: bool = False, all_instances: bool = False) -> None:
    """Remove instance(s) permanently."""
    session = DEFAULT_SESSION

    if name is None and not all_instances:
        detected = detect_current_ccmux_instance_any()
        if detected:
            session, name = detected[0], detected[1]
        else:
            console.print("[red]Error:[/red] No instance name provided and could not auto-detect.", style="bold")
            console.print("  Run from within a ccmux instance, or specify a name:")
            console.print("    [cyan]ccmux remove <name>[/cyan]")
            console.print("  To remove all instances:")
            console.print("    [cyan]ccmux remove --all[/cyan]")
            sys.exit(1)

    instances = state.get_all_instances(session)
    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        sys.exit(0)

    if name is None:
        _remove_all_instances(session, instances, yes)
    else:
        _remove_single_instance(session, name, instances, yes)


# ---------------------------------------------------------------------------
# instance_deactivate decomposed
# ---------------------------------------------------------------------------

def _deactivate_all_instances(session: str, active_instances: list, yes: bool) -> None:
    """Deactivate all active instances."""
    if not active_instances:
        console.print(f"\n[yellow]No active instances to deactivate.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating {len(active_instances)} active instance(s):[/bold yellow]")
    for inst in active_instances:
        console.print(f"  \u2022 {inst.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"Deactivate all {len(active_instances)} instance(s)?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    deactivated = 0
    for inst in active_instances:
        if kill_instance_windows(session, inst.name, inst.tmux_window_id):
            console.print(f"  [green]\u2713[/green] Deactivated '{inst.name}'")
            deactivated += 1
        else:
            console.print(f"  [yellow]Window '{inst.name}' not found or already closed[/yellow]")
            # Still kill the bash window
            kill_tmux_window(f"{bash_session_name(session)}:{inst.name}")

    notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Deactivated {deactivated} instance(s).")


def _deactivate_single_instance(session: str, name: str, instances: list, active_instances: list) -> None:
    """Deactivate a single instance."""
    instance = find_instance_by_name(instances, name)
    if instance is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        sys.exit(1)

    if instance not in active_instances:
        console.print(f"[yellow]Instance '{name}' is already inactive.[/yellow]")
        return

    console.print(f"\n[bold yellow]Deactivating instance '{name}'[/bold yellow]")

    if kill_instance_windows(session, name, instance.tmux_window_id):
        console.print(f"  [green]\u2713[/green] Deactivated '{name}'")
    else:
        console.print(f"  [yellow]Window '{name}' not found or already closed[/yellow]")

    notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Instance '{name}' deactivated.")


def do_instance_deactivate(name: Optional[str] = None, yes: bool = False) -> None:
    """Deactivate Claude Code instance(s)."""
    session = DEFAULT_SESSION
    instances = state.get_all_instances(session)

    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        sys.exit(0)

    active, _ = partition_instances_by_active(session, instances)

    if name is None:
        detected = detect_current_ccmux_instance_any()
        if detected:
            name = detected[1]

    if name is None:
        _deactivate_all_instances(session, active, yes)
    else:
        _deactivate_single_instance(session, name, instances, active)


# ---------------------------------------------------------------------------
# activate decomposed
# ---------------------------------------------------------------------------

def _activate_all(session: str, yes: bool = False) -> None:
    """Activate all inactive instances in a session."""
    instances = state.get_all_instances(session)
    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        sys.exit(0)

    _, inactive = partition_instances_by_active(session, instances)
    if not inactive:
        ensure_outer_session(session)
        console.print("\n[yellow]No inactive instances to activate.[/yellow]")
        return

    console.print(f"\n[bold cyan]Found {len(inactive)} inactive instance(s):[/bold cyan]")
    for wt in inactive:
        console.print(f"  \u2022 {wt.name}")
    console.print()

    if not yes:
        if not Confirm.ask(f"Activate all {len(inactive)} instance(s)?", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    inner = inner_session_name(session)
    inner_exists = tmux_session_exists(inner)
    activated = 0

    for i, wt in enumerate(inactive):
        is_first = not inner_exists and i == 0
        claude_session_id = str(uuid.uuid4())
        launch_cmd = build_activate_command(wt.name, wt.instance_path, claude_session_id)

        window_id = create_instance_window(session, wt.name, wt.instance_path, launch_cmd, is_first)
        if window_id:
            if is_first:
                inner_exists = True
                console.print(f"  [green]\u2713[/green] Created tmux session and activated '{wt.name}'")
            else:
                console.print(f"  [green]\u2713[/green] Activated '{wt.name}'")
            update_instance_tmux_state(wt.name, session, claude_session_id, window_id)
            activated += 1
        else:
            console.print(f"  [red]Error activating '{wt.name}'[/red]")

    ensure_outer_session(session)
    notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Activated {activated} instance(s).")


def _activate_single(session: str, name: str, yes: bool = False) -> None:
    """Activate a single instance by name."""
    instances = state.get_all_instances(session)
    if not instances:
        console.print(f"[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        sys.exit(0)

    worktree = find_instance_by_name(instances, name)
    if worktree is None:
        console.print(f"[red]Error:[/red] Instance '{name}' not found.", style="bold")
        console.print(f"List instances with: [cyan]ccmux list[/cyan]")
        sys.exit(1)

    if is_instance_window_active(session, worktree.tmux_window_id):
        ensure_outer_session(session)
        console.print(f"[yellow]Instance '{name}' already has an active tmux window.[/yellow]")
        return

    console.print(f"\n[bold cyan]Activating Claude Code instance:[/bold cyan] {name}")
    console.print(f"  Instance: {worktree.instance_path}")

    inner = inner_session_name(session)
    is_first = not tmux_session_exists(inner)
    claude_session_id = str(uuid.uuid4())
    launch_cmd = build_activate_command(name, worktree.instance_path, claude_session_id)

    window_id = create_instance_window(session, name, worktree.instance_path, launch_cmd, is_first)

    if window_id is None:
        console.print(f"[red]Error activating Claude Code[/red]", style="bold")
        sys.exit(1)

    if is_first:
        console.print(f"  [green]\u2713[/green] Created tmux session and activated '{name}'")
    else:
        select_window(inner, name)
        console.print(f"  [green]\u2713[/green] Activated '{name}'")

    update_instance_tmux_state(name, session, claude_session_id, window_id)

    ensure_outer_session(session)
    notify_sidebars(session)
    console.print(f"\n[bold green]Success![/bold green] Claude Code is running.")
    console.print(f"Attach with: [cyan]ccmux attach[/cyan]")
    auto_attach_if_outside_tmux(session, yes)


def do_instance_activate(name: Optional[str] = None, yes: bool = False) -> None:
    """Activate Claude Code in an instance."""
    session = DEFAULT_SESSION
    if name is None:
        _activate_all(session, yes)
    else:
        _activate_single(session, name, yes)


# ---------------------------------------------------------------------------
# session_kill
# ---------------------------------------------------------------------------

def do_session_kill(yes: bool = False) -> None:
    """Kill the entire ccmux session."""
    session = DEFAULT_SESSION
    instances = state.get_all_instances(session)
    inner = inner_session_name(session)

    active = [
        inst for inst in instances
        if is_instance_window_active(session, inst.tmux_window_id)
    ]

    outer = outer_session_name(session)
    if not active and not tmux_session_exists(outer):
        console.print("[yellow]No active ccmux session to kill.[/yellow]")
        return

    if active:
        console.print(f"\n[bold red]Killing ccmux session with {len(active)} active instance(s):[/bold red]")
        for inst in active:
            console.print(f"  \u2022 {inst.name}")
    else:
        console.print("\n[bold red]Killing ccmux session (no active instances)[/bold red]")

    if not yes:
        if not Confirm.ask("Kill the entire ccmux session?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    bash = bash_session_name(session)
    kill_all_ccmux_sessions(session, outer, inner, bash)
    console.print("\n[bold green]Killed ccmux session.[/bold green]")


# ---------------------------------------------------------------------------
# instance_info (default command logic)
# ---------------------------------------------------------------------------

def do_instance_info() -> None:
    """Show current instance info, or auto-attach/create."""
    detected = _detect_from_env_or_bash()

    if detected:
        session_name, instance_name, instance_data = detected
        show_instance_info(session_name, instance_name, instance_data)
        return

    session = DEFAULT_SESSION
    cwd_match = _try_cwd_match(session)
    if cwd_match:
        return

    repo_root = get_repo_root()
    if repo_root is None:
        console.print("[yellow]Not in a ccmux instance or git repository.[/yellow]\n")
        return None  # signal to cli.py to print help

    do_instance_new(yes=True)


def _detect_from_env_or_bash() -> Optional[tuple]:
    """Try env var and bash-session detection (not cwd fallback)."""
    detected = detect_current_ccmux_instance()
    if detected:
        return detected

    tmux_session = get_current_tmux_session()
    if tmux_session and tmux_session.endswith("-bash"):
        ccmux_session = ccmux_session_from_tmux(tmux_session)
        window_name = get_current_tmux_window()
        if window_name:
            instance_data = state.get_instance(window_name, ccmux_session)
            if instance_data:
                return (ccmux_session, window_name, instance_data)
    return None


def _try_cwd_match(session: str) -> bool:
    """Try matching cwd to an instance. Returns True if handled."""
    cwd = str(Path.cwd())
    found = state.find_instance_by_path(cwd, session)
    if not found:
        return False

    instance_name, instance_data = found
    is_active = (
        instance_data.tmux_window_id
        and tmux_session_exists(inner_session_name(session))
        and is_instance_window_active(session, instance_data.tmux_window_id)
    )

    if not is_active:
        console.print(f"Found instance [cyan]'{instance_name}'[/cyan]. Activating...")
        _activate_single(session, instance_name, yes=True)
        return True

    console.print(f"Instance [cyan]'{instance_name}'[/cyan] is active. Attaching...")
    ensure_outer_session(session)
    notify_sidebars(session)
    outer = outer_session_name(session)
    if "TMUX" not in os.environ:
        os.execvp("tmux", ["tmux", "attach", "-t", f"={outer}"])
    else:
        console.print(f"Already in tmux. Run: [cyan]tmux attach -t ={outer}[/cyan]")
    return True


# ---------------------------------------------------------------------------
# Other commands
# ---------------------------------------------------------------------------

def do_detach(all_clients: bool = False) -> None:
    """Detach the ccmux tmux session."""
    session = DEFAULT_SESSION
    outer = outer_session_name(session)
    if not tmux_session_exists(outer):
        console.print(f"[red]Error:[/red] No active ccmux session.", style="bold")
        sys.exit(1)
    try:
        if all_clients:
            detach_client(session=outer)
        else:
            clients = list_clients(outer)
            if not clients:
                console.print("[red]Error:[/red] No clients attached to ccmux session.", style="bold")
                sys.exit(1)
            detach_client(client_tty=clients[0])
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error detaching:[/red] {e}", style="bold")
        sys.exit(1)


def do_attach() -> None:
    """Attach to the ccmux tmux session."""
    session = DEFAULT_SESSION
    session_obj = state.get_session(session)
    if session_obj is None:
        console.print(f"[red]Error:[/red] No ccmux session found.", style="bold")
        console.print(f"\nCreate an instance with: [cyan]ccmux new[/cyan]")
        sys.exit(1)

    inner = inner_session_name(session)
    if not tmux_session_exists(inner):
        console.print(f"[red]Error:[/red] Tmux session no longer exists.", style="bold")
        console.print(f"\nThe tmux session was closed. Activate instances with: [cyan]ccmux activate[/cyan]")
        sys.exit(1)

    ensure_outer_session(session)
    notify_sidebars(session)
    outer = outer_session_name(session)
    os.execvp("tmux", ["tmux", "attach", "-t", f"={outer}"])


def do_instance_which() -> None:
    """Print the current instance name (useful for scripting)."""
    detected = detect_current_ccmux_instance_any()
    if detected is None:
        sys.exit(1)
    print(detected[1])


def do_instance_list() -> None:
    """List all instances and their tmux session status."""
    session = DEFAULT_SESSION
    instances = state.get_all_instances(session)
    if not instances:
        console.print("\n[yellow]No instances found.[/yellow]")
        console.print(f"Create one with: [cyan]ccmux new[/cyan]")
        return
    display_session_table(session)
