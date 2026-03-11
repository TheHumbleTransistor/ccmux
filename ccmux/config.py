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


def get_agent_command(repo_root: Path) -> str:
    """Return the agent launch command from ccmux.toml, or 'claude' if not configured."""
    config = load_repo_config(repo_root)
    if config is None:
        return "claude"
    return config.get("agent", {}).get("command", "claude")


def get_bash_command(repo_root: Path) -> str:
    """Return the bash shell command from ccmux.toml, or '$SHELL' if not configured."""
    config = load_repo_config(repo_root)
    if config is None:
        return "$SHELL"
    return config.get("bash", {}).get("command", "$SHELL")


def run_post_create_commands(
    repo_root: Path,
    session_path: Path,
    session_name: str,
) -> Generator[CommandEvent, None, None]:
    """Execute post_create commands from ccmux.toml, yielding structured events.

    Uses /bin/bash as the shell executable so bash-specific features
    (source, [[, nvm, etc.) work correctly.

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

    env = os.environ.copy()
    env["CCMUX_REPO_ROOT"] = str(repo_root)
    env["CCMUX_SESSION_PATH"] = str(session_path)
    env["CCMUX_SESSION_NAME"] = session_name

    for cmd in commands:
        yield CommandEvent(cmd=cmd, event_type="start")
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                executable="/bin/bash",
                cwd=str(session_path),
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
