"""Configuration file handling for ccmux - loads and executes ccmux.toml."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

console = Console()


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
    except Exception as e:
        return None


def run_post_create(
    repo_root: Path,
    session_path: Path,
    session_name: str,
) -> bool:
    """Execute post_create commands from ccmux.toml after worktree creation.

    Args:
        repo_root: Absolute path to the main git repo
        session_path: Absolute path to the new worktree
        session_name: Name of the new session

    Returns:
        True if all commands succeeded, False if any failed
    """
    config = load_repo_config(repo_root)
    if config is None:
        return True

    commands = config.get("worktree", {}).get("post_create", [])
    if not commands:
        return True

    env = os.environ.copy()
    env["CCMUX_REPO_ROOT"] = str(repo_root)
    env["CCMUX_SESSION_PATH"] = str(session_path)
    env["CCMUX_SESSION_NAME"] = session_name

    all_ok = True
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(session_path),
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                pass
            else:
                if result.stderr.strip():
                    for line in result.stderr.strip().split("\n"):
                        pass
                all_ok = False
        except Exception as e:
            all_ok = False

    return all_ok
