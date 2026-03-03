"""Tests for ccmux exception classes and CLI error handling."""

import sys
from unittest import mock

import pytest

from ccmux.exceptions import (
    ActivationError,
    AttachError,
    CcmuxError,
    DefaultBranchError,
    DetachError,
    InvalidArgumentError,
    NoSessionsFound,
    NotInCcmuxSessionError,
    NotInGitRepoError,
    SessionExistsError,
    SessionNotFoundError,
    TmuxError,
    UserAbortedError,
    WorktreeError,
)


# ---------------------------------------------------------------------------
# Exception class instantiation and attributes
# ---------------------------------------------------------------------------


class TestCcmuxError:
    def test_base_exception(self):
        e = CcmuxError("something broke")
        assert str(e) == "something broke"
        assert e.message == "something broke"
        assert e.exit_code == 1

    def test_is_exception(self):
        assert issubclass(CcmuxError, Exception)


class TestNoSessionsFound:
    def test_default(self):
        e = NoSessionsFound()
        assert str(e) == "No sessions found."
        assert e.exit_code == 0
        assert e.hint == ""

    def test_with_hint(self):
        e = NoSessionsFound("Create one with: ccmux new")
        assert e.hint == "Create one with: ccmux new"
        assert e.exit_code == 0

    def test_is_ccmux_error(self):
        assert issubclass(NoSessionsFound, CcmuxError)


class TestSessionNotFoundError:
    def test_basic(self):
        e = SessionNotFoundError("my-session")
        assert str(e) == "Session 'my-session' not found."
        assert e.name == "my-session"
        assert e.hint == ""
        assert e.exit_code == 1

    def test_with_hint(self):
        e = SessionNotFoundError("foo", "List sessions with: ccmux list")
        assert e.hint == "List sessions with: ccmux list"


class TestSessionExistsError:
    def test_basic(self):
        e = SessionExistsError("dup")
        assert str(e) == "Session 'dup' already exists."
        assert e.name == "dup"
        assert e.exit_code == 1


class TestNotInGitRepoError:
    def test_message(self):
        e = NotInGitRepoError()
        assert str(e) == "Not inside a git repository."
        assert e.exit_code == 1

    def test_message_with_path(self):
        e = NotInGitRepoError("/tmp")
        assert str(e) == "Not inside a git repository: /tmp"
        assert e.exit_code == 1


class TestDefaultBranchError:
    def test_message(self):
        e = DefaultBranchError()
        assert str(e) == "Could not detect default branch (main/master)."
        assert e.exit_code == 1


class TestUserAbortedError:
    def test_with_reason(self):
        e = UserAbortedError("Main repository already in use.")
        assert str(e) == "Main repository already in use."
        assert e.reason == "Main repository already in use."

    def test_without_reason(self):
        e = UserAbortedError()
        assert str(e) == "Aborted."
        assert e.reason == ""


class TestTmuxError:
    def test_without_detail(self):
        e = TmuxError("session creation")
        assert str(e) == "Tmux session creation failed."
        assert e.operation == "session creation"
        assert e.detail == ""

    def test_with_detail(self):
        e = TmuxError("window creation", "server not running")
        assert str(e) == "Tmux window creation failed: server not running"
        assert e.detail == "server not running"


class TestWorktreeError:
    def test_without_detail(self):
        e = WorktreeError("creation")
        assert str(e) == "Worktree creation failed."
        assert e.operation == "creation"

    def test_with_detail(self):
        e = WorktreeError("move", "permission denied")
        assert str(e) == "Worktree move failed: permission denied"
        assert e.detail == "permission denied"


class TestInvalidArgumentError:
    def test_message(self):
        e = InvalidArgumentError("Provide both old and new names")
        assert str(e) == "Provide both old and new names"
        assert e.exit_code == 1


class TestNotInCcmuxSessionError:
    def test_message(self):
        e = NotInCcmuxSessionError()
        assert str(e) == "Not in a workspace session."
        assert e.exit_code == 1


class TestActivationError:
    def test_message(self):
        e = ActivationError("my-session")
        assert str(e) == "Error activating session 'my-session'."
        assert e.name == "my-session"
        assert e.exit_code == 1


class TestDetachError:
    def test_message(self):
        e = DetachError("No active workspace to detach from.")
        assert str(e) == "No active workspace to detach from."
        assert e.reason == "No active workspace to detach from."
        assert e.exit_code == 1


class TestAttachError:
    def test_without_hint(self):
        e = AttachError("No workspace found.")
        assert str(e) == "No workspace found."
        assert e.hint == ""

    def test_with_hint(self):
        e = AttachError("No workspace found.", "Create a session with: ccmux new")
        assert e.hint == "Create a session with: ccmux new"
        assert e.exit_code == 1


# ---------------------------------------------------------------------------
# All exceptions inherit from CcmuxError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc_class",
    [
        NoSessionsFound,
        SessionNotFoundError,
        SessionExistsError,
        NotInGitRepoError,
        DefaultBranchError,
        UserAbortedError,
        TmuxError,
        WorktreeError,
        InvalidArgumentError,
        NotInCcmuxSessionError,
        ActivationError,
        DetachError,
        AttachError,
    ],
)
def test_all_inherit_from_ccmux_error(exc_class):
    assert issubclass(exc_class, CcmuxError)


# ---------------------------------------------------------------------------
# CLI integration: exception → sys.exit mapping
# ---------------------------------------------------------------------------


class TestCliExceptionHandling:
    """Test that cli.main() catches exceptions and exits correctly."""

    def _run_main_with_exception(self, exception):
        """Run cli.main() where app() raises the given exception."""
        with mock.patch(
            "ccmux.cli.check_tmux_installed", return_value=True
        ), mock.patch(
            "ccmux.cli.check_backend_installed", return_value=True
        ), mock.patch(
            "ccmux.cli.stale_sessions_running", return_value=False
        ), mock.patch("ccmux.cli.app", side_effect=exception), mock.patch(
            "ccmux.cli.console"
        ) as mock_console:
            from ccmux.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            return exc_info.value.code, mock_console

    def test_no_sessions_found_exits_0(self):
        code, mock_console = self._run_main_with_exception(NoSessionsFound())
        assert code == 0
        mock_console.print.assert_any_call("[yellow]No sessions found.[/yellow]")

    def test_no_sessions_found_with_hint(self):
        code, mock_console = self._run_main_with_exception(
            NoSessionsFound("Create one with: ccmux new")
        )
        assert code == 0
        mock_console.print.assert_any_call("  Create one with: ccmux new")

    def test_session_not_found_exits_1(self):
        code, mock_console = self._run_main_with_exception(SessionNotFoundError("foo"))
        assert code == 1

    def test_session_not_found_with_hint(self):
        code, mock_console = self._run_main_with_exception(
            SessionNotFoundError("foo", "List sessions with: ccmux list")
        )
        assert code == 1
        mock_console.print.assert_any_call("  List sessions with: ccmux list")

    def test_not_in_git_repo_exits_1(self):
        code, _ = self._run_main_with_exception(NotInGitRepoError())
        assert code == 1

    def test_keyboard_interrupt_exits_130(self):
        code, _ = self._run_main_with_exception(KeyboardInterrupt())
        assert code == 130

    def test_session_exists_exits_1(self):
        code, _ = self._run_main_with_exception(SessionExistsError("dup"))
        assert code == 1

    def test_tmux_error_exits_1(self):
        code, _ = self._run_main_with_exception(TmuxError("session creation"))
        assert code == 1

    def test_worktree_error_exits_1(self):
        code, _ = self._run_main_with_exception(WorktreeError("creation", "fail"))
        assert code == 1

    def test_attach_error_with_hint(self):
        code, mock_console = self._run_main_with_exception(
            AttachError("No workspace found.", "Create a session with: ccmux new")
        )
        assert code == 1
        mock_console.print.assert_any_call("  Create a session with: ccmux new")
