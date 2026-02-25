"""Demo snapshot builder for sidebar testing."""

import random

from ccmux.ui.sidebar.snapshot import SessionSnapshot

# Static session metadata:
#   (session_name, repo, session_type, branch, short_sha, +lines, -lines)
_SESSION_META = [
    ("main",      "my-project", "main",     "main",             "a1b2c3d", 15,   3),
    ("feat-auth", "my-project", "worktree", "feat/auth-system", "e4f5a6b", 47,  12),
    ("fix-bug",   "my-project", "worktree", None,               "7c8d9e0",  3,   1),
    ("default",   "other-repo", "main",     "main",             "f1a2b3c",  8,   0),
    ("refactor",  "other-repo", "worktree", "refactor/cleanup", "d4e5f6a", 128, 89),
]


class DemoProvider:
    """Stateful demo snapshot provider with per-session activity cycling.

    Each session independently cycles: idle → activity → bell → idle with
    randomised durations.  Durations are tuned so ~3 of 5 sessions are in
    the *activity* state at any given tick.

    A fixed RNG seed keeps the demo deterministic across runs.
    """

    # Tick-count ranges for each state.
    # Average cycle: 18.5 (activity) + 6 (bell) + 7 (idle) = 31.5 ticks.
    # Fraction in activity ≈ 18.5 / 31.5 ≈ 59 % → 5 × 0.59 ≈ 3 sessions.
    _ACTIVITY_TICKS = (12, 25)
    _BELL_TICKS = (4, 8)
    _IDLE_TICKS = (4, 10)

    def __init__(self) -> None:
        self._current = "main"
        self._dismissed_bells: set[str] = set()
        self._rng = random.Random(42)
        # Per-session state: {name: [state, ticks_remaining]}
        # state is None | "activity" | "bell"
        self._states: dict[str, list] = {}
        self._init_staggered()

    def _init_staggered(self) -> None:
        """Seed sessions at staggered points so they don't transition together."""
        for i, (name, *_) in enumerate(_SESSION_META):
            if i < 3:
                # First three start in activity, each offset into the cycle
                ttl = self._rng.randint(*self._ACTIVITY_TICKS) - i * 4
                self._states[name] = ["activity", max(2, ttl)]
            else:
                # Remaining start idle with short staggered waits
                self._states[name] = [None, self._rng.randint(2, 7)]

    def _advance_states(self) -> None:
        """Tick every session's independent state machine."""
        for name in self._states:
            state, ttl = self._states[name]
            ttl -= 1
            if ttl <= 0:
                if state is None:
                    self._states[name] = [
                        "activity", self._rng.randint(*self._ACTIVITY_TICKS),
                    ]
                elif state == "activity":
                    self._states[name] = [
                        "bell", self._rng.randint(*self._BELL_TICKS),
                    ]
                else:  # bell → idle
                    self._states[name] = [
                        None, self._rng.randint(*self._IDLE_TICKS),
                    ]
            else:
                self._states[name] = [state, ttl]

    def select(self, session_name: str) -> None:
        """Set the current session (called on click)."""
        self._current = session_name
        # Dismiss any bell on the selected session (mirrors real tmux bell-clear)
        self._dismissed_bells.add(session_name)

    async def __call__(self) -> list[SessionSnapshot]:
        """Build the snapshot for the current tick, then advance."""
        sessions = []
        for name, repo, stype, branch, sha, added, removed in _SESSION_META:
            alert = self._states[name][0]
            # Suppress bells the user dismissed by clicking
            if name in self._dismissed_bells and alert == "bell":
                alert = None
            sessions.append(SessionSnapshot(
                repo, name, stype, True,
                name == self._current, alert,
                branch=branch, short_sha=sha,
                lines_added=added, lines_removed=removed,
            ))

        self._advance_states()
        # Clear dismissals for sessions that have left the bell state
        self._dismissed_bells = {
            n for n in self._dismissed_bells
            if self._states[n][0] == "bell"
        }
        return sessions


def make_demo_provider() -> DemoProvider:
    """Return a DemoProvider instance (callable + select method)."""
    return DemoProvider()
