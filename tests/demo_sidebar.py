"""Demo snapshot builder for sidebar testing."""

from collections.abc import Awaitable, Callable

from ccmux.ui.sidebar.snapshot import SessionSnapshot


def _base_sessions(
    current: str = "main",
    alerts: dict[str, str | None] | None = None,
    extra_session: bool = False,
) -> list[SessionSnapshot]:
    """Build the standard set of demo sessions with overrides."""
    alerts = alerts or {}
    sessions = [
        SessionSnapshot(
            "my-project", "main", "main", True,
            current == "main", alerts.get("main"),
            branch="main", short_sha="a1b2c3d",
            lines_added=15, lines_removed=3,
        ),
        SessionSnapshot(
            "my-project", "feat-auth", "worktree", True,
            current == "feat-auth", alerts.get("feat-auth"),
            branch="feat/auth-system", short_sha="e4f5a6b",
            lines_added=47, lines_removed=12,
        ),
        SessionSnapshot(
            "my-project", "fix-bug", "worktree", False,
            current == "fix-bug", alerts.get("fix-bug"),
            branch=None, short_sha="7c8d9e0",
            lines_added=3, lines_removed=1,
        ),
        SessionSnapshot(
            "other-repo", "default", "main", True,
            current == "default", alerts.get("default"),
            branch="main", short_sha="f1a2b3c",
            lines_added=8, lines_removed=0,
        ),
        SessionSnapshot(
            "other-repo", "refactor", "worktree", False,
            False, None,
            branch="refactor/cleanup", short_sha="d4e5f6a",
            lines_added=128, lines_removed=89,
        ),
    ]
    if extra_session:
        sessions.append(SessionSnapshot(
            "other-repo", "hotfix", "worktree", True,
            False, "bell",
            branch="hotfix/urgent", short_sha="b7c8d9e",
            lines_added=5, lines_removed=2,
        ))
    return sessions


# Scripted alert phases: (ticks, kwargs WITHOUT current — current is user-controlled)
_PHASES: list[tuple[int, dict]] = [
    # 1. Resting — everything quiet
    (8, {}),
    # 2. Activity on feat-auth (breathing dot)
    (8, dict(alerts={"feat-auth": "activity"})),
    # 3. Bell on default (red flash)
    (8, dict(alerts={"default": "bell"})),
    # 4. Activity on main
    (8, dict(alerts={"main": "activity"})),
    # 5. Activity on feat-auth again
    (8, dict(alerts={"feat-auth": "activity"})),
    # 6. Extra session appears (tests rebuild path)
    (8, dict(extra_session=True)),
    # 7. Back to quiet
    (6, {}),
]

_TOTAL_TICKS = sum(t for t, _ in _PHASES)


class DemoProvider:
    """Stateful demo snapshot provider with user-controlled current session."""

    def __init__(self) -> None:
        self._tick = 0
        self._current = "main"

    def select(self, session_name: str) -> None:
        """Set the current session (called on click)."""
        self._current = session_name

    async def __call__(self) -> list[SessionSnapshot]:
        """Build the snapshot for the current tick, then advance."""
        pos = self._tick % _TOTAL_TICKS
        for duration, kwargs in _PHASES:
            if pos < duration:
                snap = _base_sessions(current=self._current, **kwargs)
                break
            pos -= duration
        else:
            snap = _base_sessions(current=self._current)
        self._tick += 1
        return snap


def make_demo_provider() -> DemoProvider:
    """Return a DemoProvider instance (callable + select method)."""
    return DemoProvider()
