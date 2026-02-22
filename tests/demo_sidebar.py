"""Demo snapshot builder for sidebar testing."""

from collections.abc import Awaitable, Callable

from ccmux.ui.sidebar.snapshot import InstanceSnapshot


def build_demo_snapshot(tick: int) -> list[InstanceSnapshot]:
    """Build varying snapshot data to exercise refresh/rebuild paths."""
    # Cycle current instance among three instances
    current_idx = tick % 3
    # Cycle alert states: None -> bell -> activity -> None
    alert_cycle = [None, "bell", "activity", None]
    alert_for = lambda offset: alert_cycle[(tick + offset) % len(alert_cycle)]

    base = [
        InstanceSnapshot("my-project", "main", "main", True, current_idx == 0, alert_for(0),
                         branch="main", short_sha="a1b2c3d", lines_added=15, lines_removed=3),
        InstanceSnapshot("my-project", "feat-auth", "worktree", True, current_idx == 1, alert_for(1),
                         branch="feat/auth-system", short_sha="e4f5a6b", lines_added=47, lines_removed=12),
        InstanceSnapshot("my-project", "fix-bug", "worktree", False, current_idx == 2, alert_for(2),
                         branch=None, short_sha="7c8d9e0", lines_added=3, lines_removed=1),
        InstanceSnapshot("other-repo", "default", "main", True, False, alert_for(3),
                         branch="main", short_sha="f1a2b3c", lines_added=8, lines_removed=0),
        InstanceSnapshot("other-repo", "refactor", "worktree", False, False, None,
                         branch="refactor/cleanup", short_sha="d4e5f6a", lines_added=128, lines_removed=89),
    ]

    # Every 8th tick, add an extra instance (tests full rebuild path)
    if (tick // 4) % 2 == 1:
        base.append(InstanceSnapshot("other-repo", "hotfix", "worktree", True, False, "bell",
                                     branch="hotfix/urgent", short_sha="b7c8d9e", lines_added=5, lines_removed=2))

    return base


def make_demo_provider() -> Callable[[], Awaitable[list[InstanceSnapshot]]]:
    """Return an async closure that auto-increments the demo tick."""
    tick = 0

    async def _provider() -> list[InstanceSnapshot]:
        nonlocal tick
        snapshot = build_demo_snapshot(tick)
        tick += 1
        return snapshot

    return _provider
