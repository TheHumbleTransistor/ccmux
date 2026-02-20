"""Demo snapshot builder for sidebar testing."""


def build_demo_snapshot(tick: int) -> list[tuple]:
    """Build varying snapshot data to exercise refresh/rebuild paths."""
    # Cycle current instance among three instances
    current_idx = tick % 3
    # Cycle alert states: None -> bell -> activity -> None
    alert_cycle = [None, "bell", "activity", None]
    alert_for = lambda offset: alert_cycle[(tick + offset) % len(alert_cycle)]

    base = [
        ("my-project", "main", "main", True, current_idx == 0, alert_for(0)),
        ("my-project", "feat-auth", "worktree", True, current_idx == 1, alert_for(1)),
        ("my-project", "fix-bug", "worktree", False, current_idx == 2, alert_for(2)),
        ("other-repo", "default", "main", True, False, alert_for(3)),
        ("other-repo", "refactor", "worktree", False, False, None),
    ]

    # Every 8th tick, add an extra instance (tests full rebuild path)
    if (tick // 4) % 2 == 1:
        base.append(("other-repo", "hotfix", "worktree", True, False, "bell"))

    return base
