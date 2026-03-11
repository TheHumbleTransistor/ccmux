"""Configuration file handling for ccmux - loads and executes ccmux.toml."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass
class CommandEvent:
    """Structured event emitted by run_post_create_commands()."""

    cmd: str
    event_type: str  # "start", "stdout", "success", "failure", "error"
    data: str = ""
    returncode: int = 0


def load_repo_config(repo_root: Path) -> Optional[dict]:
    """Load ccmux.toml from a repository root.

    Args:
        repo_root: Path to the git repository root

    Returns:
        Parsed config dict, or None if no config file exists
    """
    config_path = repo_root / "ccmux.toml"
    if not config_path.exists():
        return None

    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def _warn_deprecated_key(section: str, old_key: str, new_key: str) -> None:
    """Print a deprecation warning for a renamed config key."""
    import sys

    print(
        f"ccmux: [agent].{old_key} is deprecated, use [agent].{new_key} instead",
        file=sys.stderr,
    )


def _resolve_launch(value) -> str:
    """Normalize a launch value to a single shell command string.

    Accepts a string or a list of strings. Lists are joined with ' && '
    so the last command is the long-running one.
    """
    if isinstance(value, list):
        return " && ".join(value)
    return value


def get_agent_launch(repo_root: Path) -> str:
    """Return the agent launch command from ccmux.toml, or 'claude' if not configured.

    Reads [agent].launch first. Falls back to deprecated [agent].command with a warning.
    The value can be a string or a list of strings (joined with &&).
    """
    config = load_repo_config(repo_root)
    if config is None:
        return "claude"
    agent = config.get("agent", {})
    if "launch" in agent:
        return _resolve_launch(agent["launch"])
    if "command" in agent:
        _warn_deprecated_key("agent", "command", "launch")
        return _resolve_launch(agent["command"])
    return "claude"


def get_bash_launch(repo_root: Path) -> str:
    """Return the bash shell command from ccmux.toml, or '$SHELL' if not configured.

    Reads [bash].launch first. Falls back to deprecated [bash].command with a warning.
    The value can be a string or a list of strings (joined with &&).
    """
    config = load_repo_config(repo_root)
    if config is None:
        return "$SHELL"
    bash = config.get("bash", {})
    if "launch" in bash:
        return _resolve_launch(bash["launch"])
    if "command" in bash:
        _warn_deprecated_key("bash", "command", "launch")
        return _resolve_launch(bash["command"])
    return "$SHELL"


def _execute_commands(
    commands: list[str],
    cwd: Path,
    env: dict[str, str],
) -> Generator[CommandEvent, None, None]:
    """Execute shell commands, yielding structured events.

    Uses /bin/bash as the shell executable so bash-specific features
    (source, [[, nvm, etc.) work correctly.
    """
    for cmd in commands:
        yield CommandEvent(cmd=cmd, event_type="start")
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                executable="/bin/bash",
                cwd=str(cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                yield CommandEvent(cmd=cmd, event_type="stdout", data=line.rstrip("\n"))
            proc.wait()
            if proc.returncode == 0:
                yield CommandEvent(cmd=cmd, event_type="success")
            else:
                yield CommandEvent(
                    cmd=cmd, event_type="failure", returncode=proc.returncode
                )
        except Exception as e:
            yield CommandEvent(cmd=cmd, event_type="error", data=str(e))


def _build_hook_env(repo_root: Path, session_path: Path, session_name: str) -> dict[str, str]:
    """Build the environment dict for hook commands."""
    env = os.environ.copy()
    env["CCMUX_REPO_ROOT"] = str(repo_root)
    env["CCMUX_SESSION_PATH"] = str(session_path)
    env["CCMUX_SESSION_NAME"] = session_name
    return env


def run_post_create_commands(
    repo_root: Path,
    session_path: Path,
    session_name: str,
) -> Generator[CommandEvent, None, None]:
    """Execute [worktree].post_create commands from ccmux.toml.

    Only runs for worktree sessions. See also run_session_post_create_commands()
    for commands that run on every session.

    Args:
        repo_root: Absolute path to the main git repo
        session_path: Absolute path to the new worktree
        session_name: Name of the new session

    Yields:
        CommandEvent objects describing execution progress
    """
    config = load_repo_config(repo_root)
    if config is None:
        return

    commands = config.get("worktree", {}).get("post_create", [])
    if not commands:
        return

    env = _build_hook_env(repo_root, session_path, session_name)
    yield from _execute_commands(commands, session_path, env)


def run_session_post_create_commands(
    repo_root: Path,
    session_path: Path,
    session_name: str,
) -> Generator[CommandEvent, None, None]:
    """Execute [session].post_create commands from ccmux.toml.

    Runs for every session created via ``ccmux new``, regardless of whether
    it is a worktree or main-repo session.

    Args:
        repo_root: Absolute path to the main git repo
        session_path: Absolute path to the session working directory
        session_name: Name of the new session

    Yields:
        CommandEvent objects describing execution progress
    """
    config = load_repo_config(repo_root)
    if config is None:
        return

    commands = config.get("session", {}).get("post_create", [])
    if not commands:
        return

    env = _build_hook_env(repo_root, session_path, session_name)
    yield from _execute_commands(commands, session_path, env)


def run_repo_init_commands(
    repo_root: Path,
    session_path: Path,
    session_name: str,
) -> Generator[CommandEvent, None, None]:
    """Execute [repo].init commands from ccmux.toml.

    Intended to run only once — the first time a session is created for a repo
    (i.e. when no other sessions for that repo exist yet). The caller is
    responsible for checking this condition.

    Args:
        repo_root: Absolute path to the main git repo
        session_path: Absolute path to the session working directory
        session_name: Name of the new session

    Yields:
        CommandEvent objects describing execution progress
    """
    config = load_repo_config(repo_root)
    if config is None:
        return

    commands = config.get("repo", {}).get("init", [])
    if not commands:
        return

    env = _build_hook_env(repo_root, session_path, session_name)
    yield from _execute_commands(commands, session_path, env)
