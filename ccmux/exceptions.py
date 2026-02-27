"""Exception classes for ccmux.

Business logic raises these exceptions; the CLI layer catches and presents them.
No rich markup — plain text messages + structured fields. CLI adds formatting.
"""


class CcmuxError(Exception):
    """Base exception for all ccmux errors."""

    exit_code: int = 1

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message)


class NoSessionsFound(CcmuxError):
    """No sessions exist (informational, not an error)."""

    exit_code: int = 0

    def __init__(self, hint: str = ""):
        self.hint = hint
        super().__init__("No sessions found.")


class SessionNotFoundError(CcmuxError):
    """A named session does not exist."""

    def __init__(self, name: str, hint: str = ""):
        self.name = name
        self.hint = hint
        super().__init__(f"Session '{name}' not found.")


class SessionExistsError(CcmuxError):
    """A session with that name already exists."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Session '{name}' already exists.")


class NotInGitRepoError(CcmuxError):
    """The current directory is not inside a git repository."""

    def __init__(self, path: str = ""):
        if path:
            super().__init__(f"Not inside a git repository: {path}")
        else:
            super().__init__("Not inside a git repository.")


class DefaultBranchError(CcmuxError):
    """Could not detect the default branch."""

    def __init__(self):
        super().__init__("Could not detect default branch (main/master).")


class UserAbortedError(CcmuxError):
    """The user aborted an operation."""

    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(reason or "Aborted.")


class TmuxError(CcmuxError):
    """A tmux operation failed."""

    def __init__(self, operation: str, detail: str = ""):
        self.operation = operation
        self.detail = detail
        msg = f"Tmux {operation} failed."
        if detail:
            msg = f"Tmux {operation} failed: {detail}"
        super().__init__(msg)


class WorktreeError(CcmuxError):
    """A git worktree operation failed."""

    def __init__(self, operation: str, detail: str = ""):
        self.operation = operation
        self.detail = detail
        msg = f"Worktree {operation} failed."
        if detail:
            msg = f"Worktree {operation} failed: {detail}"
        super().__init__(msg)


class InvalidArgumentError(CcmuxError):
    """Invalid or missing CLI arguments."""

    def __init__(self, message: str):
        super().__init__(message)


class NotInCcmuxSessionError(CcmuxError):
    """Not currently inside a ccmux session."""

    def __init__(self):
        super().__init__("Not in a workspace session.")


class ActivationError(CcmuxError):
    """Failed to activate a session."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Error activating session '{name}'.")


class DetachError(CcmuxError):
    """Failed to detach from a session."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AttachError(CcmuxError):
    """Failed to attach to a session."""

    def __init__(self, reason: str, hint: str = ""):
        self.reason = reason
        self.hint = hint
        super().__init__(reason)
