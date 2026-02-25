"""Session dataclasses for ccmux state management."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    """Base class for a ccmux session (worktree or main repo)."""
    name: str
    repo_path: str
    session_path: str
    tmux_cc_window_id: Optional[str] = None
    tmux_bash_window_id: Optional[str] = None
    claude_session_id: Optional[str] = None
    id: int = 0

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
            "tmux_window_ids": {
                "claude_code": self.tmux_cc_window_id,
                "bash_terminal": self.tmux_bash_window_id,
            },
            "id": self.id,
        }
        if self.claude_session_id:
            d["claude_session_id"] = self.claude_session_id
        return d

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Session":
        """Factory — returns WorktreeSession or MainRepoSession."""
        window_ids = data.get("tmux_window_ids", {})
        kwargs = dict(
            name=name,
            repo_path=data["repo_path"],
            session_path=data.get("session_path") or data.get("instance_path"),
            tmux_cc_window_id=window_ids.get("claude_code"),
            tmux_bash_window_id=window_ids.get("bash_terminal"),
            claude_session_id=data.get("claude_session_id"),
            id=data.get("id", 0),
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
