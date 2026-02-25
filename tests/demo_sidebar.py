"""Demo snapshot builder for sidebar testing."""

import random

from ccmux.ui.sidebar.snapshot import SessionSnapshot

# Static session metadata:
#   (session_name, repo, session_type, branch, short_sha, +lines, -lines, session_id, tmux_cc_window_id)
_SESSION_META = [
    ("main",      "my-project", "main",     "main",             "a1b2c3d", 15,   3, 1, "@100"),
    ("feat-auth", "my-project", "worktree", "feat/auth-system", "e4f5a6b", 47,  12, 2, "@101"),
    ("fix-bug",   "my-project", "worktree", None,               "7c8d9e0",  3,   1, 3, "@102"),
    ("default",   "other-repo", "main",     "main",             "f1a2b3c",  8,   0, 4, "@103"),
    ("refactor",  "other-repo", "worktree", "refactor/cleanup", "d4e5f6a", 128, 89, 5, "@104"),
]


class DemoProvider:
    """Stateful demo snapshot provider with per-session activity cycling.

    Each session independently cycles: idle → activity → bell, where bell
    is sticky and only cleared by clicking (select).  Without user
    interaction all sessions eventually converge to the bell state.

    A fixed RNG seed keeps the demo deterministic across runs.
    """

    _ACTIVITY_TICKS = (12, 25)
    _IDLE_TICKS = (4, 10)

    def __init__(self) -> None:
        self._current = "main"
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
            if state == "bell":
                continue  # sticky — only cleared by select()
            ttl -= 1
            if ttl <= 0:
                if state is None:
                    self._states[name] = [
                        "activity", self._rng.randint(*self._ACTIVITY_TICKS),
                    ]
                else:  # activity → bell (sticky)
                    self._states[name] = ["bell", 0]
            else:
                self._states[name] = [state, ttl]

    def select(self, session_name: str) -> None:
        """Set the current session (called on click)."""
        self._current = session_name
        # Clear bell on clicked session — transition back to idle
        if self._states.get(session_name, [None])[0] == "bell":
            self._states[session_name] = [None, self._rng.randint(*self._IDLE_TICKS)]

    async def __call__(self) -> list[SessionSnapshot]:
        """Build the snapshot for the current tick, then advance."""
        sessions = []
        for name, repo, stype, branch, sha, added, removed, sid, wid in _SESSION_META:
            sessions.append(SessionSnapshot(
                repo, name, stype, True,
                name == self._current, self._states[name][0],
                session_id=sid, tmux_cc_window_id=wid, branch=branch, short_sha=sha,
                lines_added=added, lines_removed=removed,
            ))

        self._advance_states()
        return sessions


def make_demo_provider() -> DemoProvider:
    """Return a DemoProvider instance (callable + select method)."""
    return DemoProvider()
