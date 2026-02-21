"""Session dataclass for ccmux state management."""

from dataclasses import dataclass, field
from typing import Optional

from ccmux.state.instance import Instance


@dataclass
class Session:
    """A ccmux session containing instances."""
    name: str
    tmux_session_id: Optional[str] = None
    instances: dict[str, Instance] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tmux_session_id": self.tmux_session_id,
            "instances": {n: i.to_dict() for n, i in self.instances.items()},
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "Session":
        """Construct a Session from raw state dict."""
        raw = data.get("instances", {})
        instances = {n: Instance.from_dict(n, d) for n, d in raw.items()}
        return cls(
            name=name,
            tmux_session_id=data.get("tmux_session_id"),
            instances=instances,
        )
