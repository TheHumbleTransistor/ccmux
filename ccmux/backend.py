"""Backend abstraction for AI coding tools (Claude Code, OpenCode, etc.).

Each backend encapsulates all tool-specific behavior: binary detection,
command construction, session data management, and display strings.
"""

import re
import shutil
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class Backend(Protocol):
    """Protocol defining the interface for an AI coding tool backend."""

    @property
    def name(self) -> str:
        """Short identifier used in config and state (e.g. 'claude', 'opencode')."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name for display in messages (e.g. 'Claude Code')."""
        ...

    @property
    def binary_name(self) -> str:
        """Name of the CLI binary to check on PATH (e.g. 'claude', 'opencode')."""
        ...

    @property
    def env_vars_to_unset(self) -> list[str]:
        """Environment variables to unset before launching the tool."""
        ...

    def check_installed(self) -> bool:
        """Return True if the backend's CLI binary is available on PATH."""
        ...

    def install_instructions(self) -> list[str]:
        """Return lines of text describing how to install the tool."""
        ...

    def build_launch_command(
        self,
        name: str,
        session_id: str,
        resume: bool = False,
    ) -> str:
        """Build the shell command fragment to launch the tool.

        Args:
            name: The ccmux session name (set as CCMUX_SESSION env var).
            session_id: Unique session identifier for conversation continuity.
            resume: If True, attempt to resume an existing session.

        Returns:
            A shell command string (without the CCMUX_SESSION export or shell loop;
            those are added by the caller).
        """
        ...

    def project_dir(self, session_path: str) -> Optional[Path]:
        """Compute the tool's project data directory for a given session path.

        Returns None if the tool doesn't use project-local data directories.
        """
        ...

    def migrate_session_data(
        self,
        old_path: str,
        new_path: str,
        session_id: str,
    ) -> bool:
        """Copy session data from old project dir to new after a rename/move.

        Returns True if anything was copied, False otherwise.
        """
        ...


class ClaudeCodeBackend:
    """Backend implementation for Anthropic's Claude Code CLI."""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    @property
    def binary_name(self) -> str:
        return "claude"

    @property
    def env_vars_to_unset(self) -> list[str]:
        return ["CLAUDECODE"]

    def check_installed(self) -> bool:
        return shutil.which("claude") is not None

    def install_instructions(self) -> list[str]:
        return [
            "Install Claude Code:",
            "  npm install -g @anthropic-ai/claude-code",
            "",
            "For more info: https://docs.anthropic.com/en/docs/claude-code",
        ]

    def build_launch_command(
        self,
        name: str,
        session_id: str,
        resume: bool = False,
    ) -> str:
        if resume:
            return f"claude --resume {session_id} || claude"
        return f"claude --session-id {session_id}"

    def project_dir(self, session_path: str) -> Optional[Path]:
        encoded = re.sub(r"[^a-zA-Z0-9]", "-", session_path)
        return Path.home() / ".claude" / "projects" / encoded

    def migrate_session_data(
        self,
        old_path: str,
        new_path: str,
        session_id: str,
    ) -> bool:
        old_dir = self.project_dir(old_path)
        new_dir = self.project_dir(new_path)
        if old_dir is None or new_dir is None or not old_dir.exists():
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


class OpenCodeBackend:
    """Backend implementation for OpenCode CLI."""

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def display_name(self) -> str:
        return "OpenCode"

    @property
    def binary_name(self) -> str:
        return "opencode"

    @property
    def env_vars_to_unset(self) -> list[str]:
        return []

    def check_installed(self) -> bool:
        return shutil.which("opencode") is not None

    def install_instructions(self) -> list[str]:
        return [
            "Install OpenCode:",
            "  curl -fsSL https://opencode.ai/install | bash",
            "  # or: npm install -g opencode-ai",
            "  # or: brew install anomalyco/tap/opencode",
            "",
            "For more info: https://opencode.ai/docs",
        ]

    def build_launch_command(
        self,
        name: str,
        session_id: str,
        resume: bool = False,
    ) -> str:
        # OpenCode manages sessions internally via its TUI;
        # no CLI flags for session selection are needed.
        return "opencode"

    def project_dir(self, session_path: str) -> Optional[Path]:
        # OpenCode stores data in ~/.local/share/opencode/ but does not use
        # per-project directories in the same way as Claude Code.
        return None

    def migrate_session_data(
        self,
        old_path: str,
        new_path: str,
        session_id: str,
    ) -> bool:
        # OpenCode manages its own session data internally;
        # no manual migration is needed.
        return False


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, type] = {
    "claude": ClaudeCodeBackend,
    "opencode": OpenCodeBackend,
}

_BACKEND_INSTANCES: dict[str, Backend] = {}

DEFAULT_BACKEND_NAME = "claude"


def get_backend(name: str) -> Backend:
    """Look up a backend by its short name. Raises ValueError if unknown.

    Instances are cached since backends are stateless.
    """
    if name not in _BACKEND_INSTANCES:
        cls = _BACKENDS.get(name)
        if cls is None:
            known = ", ".join(sorted(_BACKENDS))
            raise ValueError(f"Unknown backend '{name}'. Known backends: {known}")
        _BACKEND_INSTANCES[name] = cls()
    return _BACKEND_INSTANCES[name]


def get_available_backends() -> list[str]:
    """Return the list of registered backend names."""
    return sorted(_BACKENDS.keys())


def get_default_backend() -> Backend:
    """Return the default backend (Claude Code)."""
    return get_backend(DEFAULT_BACKEND_NAME)


def _reset_cache() -> None:
    """Clear the backend instance cache. Intended for test teardowns."""
    _BACKEND_INSTANCES.clear()
