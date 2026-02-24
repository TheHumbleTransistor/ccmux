"""Session dataclasses for ccmux state management."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    """Base class for a ccmux session (worktree or main repo)."""
    name: str
    repo_path: str
    session_path: str
    tmux_window_id: Optional[str] = None
    claude_session_id: Optional[str] = None

    @property
    def is_worktree(self) -> bool:
        raise NotImplementedError

    @property
    def session_type(self) -> str:
        raise NotImplementedError

    def to_dict(self) -> dict:
        d = {
            "repo_path": self.repo_path,
            "session_path": self.session_path,
            "is_worktree": self.is_worktree,
            "tmux_window_id": self.tmux_window_id,
        }
        if self.claude_session_id:
            d["claude_session_id"] = self.claude_session_id
        return d

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Session":
        """Factory — returns WorktreeSession or MainRepoSession."""
        kwargs = dict(
            name=name,
            repo_path=data["repo_path"],
            session_path=data.get("session_path") or data.get("instance_path"),
            tmux_window_id=data.get("tmux_window_id"),
            claude_session_id=data.get("claude_session_id"),
        )
        if data.get("is_worktree", True):
            return WorktreeSession(**kwargs)
        return MainRepoSession(**kwargs)


@dataclass
class WorktreeSession(Session):
    @property
    def is_worktree(self) -> bool:
        return True

    @property
    def session_type(self) -> str:
        return "worktree"


@dataclass
class MainRepoSession(Session):
    @property
    def is_worktree(self) -> bool:
        return False

    @property
    def session_type(self) -> str:
        return "main"
