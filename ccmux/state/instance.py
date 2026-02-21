"""Instance dataclasses for ccmux state management."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Instance:
    """Base class for a ccmux instance (worktree or main repo)."""
    name: str
    repo_path: str
    instance_path: str
    tmux_window_id: Optional[str] = None

    @property
    def is_worktree(self) -> bool:
        raise NotImplementedError

    @property
    def instance_type(self) -> str:
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {
            "repo_path": self.repo_path,
            "instance_path": self.instance_path,
            "is_worktree": self.is_worktree,
            "tmux_window_id": self.tmux_window_id,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Instance":
        """Factory — returns WorktreeInstance or MainRepoInstance."""
        kwargs = dict(
            name=name,
            repo_path=data["repo_path"],
            instance_path=data["instance_path"],
            tmux_window_id=data.get("tmux_window_id"),
        )
        if data.get("is_worktree", True):
            return WorktreeInstance(**kwargs)
        return MainRepoInstance(**kwargs)


@dataclass
class WorktreeInstance(Instance):
    @property
    def is_worktree(self) -> bool:
        return True

    @property
    def instance_type(self) -> str:
        return "worktree"


@dataclass
class MainRepoInstance(Instance):
    @property
    def is_worktree(self) -> bool:
        return False

    @property
    def instance_type(self) -> str:
        return "main"
