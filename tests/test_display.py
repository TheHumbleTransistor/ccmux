"""Tests for ccmux.display — session table and info display."""

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from ccmux.display import display_session_table, show_session_info
from ccmux.state.session import MainRepoSession, WorktreeSession


def _test_console(output):
    """Create a Console suitable for test output capture (no color, wide enough)."""
    return Console(file=output, no_color=True, width=200)


def _make_session(name, backend_name="claude", is_worktree=True, **kwargs):
    """Helper to create a session object for testing."""
    defaults = dict(
        name=name,
        repo_path="/repos/myrepo",
        session_path=f"/repos/myrepo/.ccmux/worktrees/{name}",
        tmux_cc_window_id=None,
        tmux_bash_window_id=None,
        claude_session_id="sess-id-1",
        backend_name=backend_name,
    )
    defaults.update(kwargs)
    cls = WorktreeSession if is_worktree else MainRepoSession
    return cls(**defaults)


class TestDisplaySessionTable:
    """Tests for display_session_table() backend column logic."""

    @patch("ccmux.display.state")
    @patch("ccmux.display.is_session_window_active", return_value=False)
    @patch("ccmux.display.get_branch_name", return_value="main")
    def test_no_backend_column_when_single_backend(
        self, mock_branch, mock_active, mock_state
    ):
        """Backend column is hidden when all sessions use the same backend."""
        sessions = [
            _make_session("sess-1", backend_name="claude"),
            _make_session("sess-2", backend_name="claude"),
        ]
        mock_state.get_all_sessions.return_value = sessions

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            display_session_table()

        text = output.getvalue()
        assert "Backend" not in text

    @patch("ccmux.display.state")
    @patch("ccmux.display.is_session_window_active", return_value=False)
    @patch("ccmux.display.get_branch_name", return_value="main")
    def test_backend_column_shown_when_mixed_backends(
        self, mock_branch, mock_active, mock_state
    ):
        """Backend column appears when sessions use different backends."""
        sessions = [
            _make_session("sess-1", backend_name="claude"),
            _make_session("sess-2", backend_name="opencode"),
        ]
        mock_state.get_all_sessions.return_value = sessions

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            display_session_table()

        text = output.getvalue()
        assert "Backend" in text
        assert "Claude Code" in text
        assert "OpenCode" in text

    @patch("ccmux.display.state")
    def test_no_sessions_message(self, mock_state):
        """Shows a message when there are no sessions."""
        mock_state.get_all_sessions.return_value = []

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            display_session_table()

        text = output.getvalue()
        assert "No sessions found" in text

    @patch("ccmux.display.state")
    @patch("ccmux.display.is_session_window_active", return_value=False)
    @patch("ccmux.display.get_branch_name", return_value="main")
    def test_active_inactive_count(self, mock_branch, mock_active, mock_state):
        """Total and active/inactive counts are displayed."""
        sessions = [
            _make_session("sess-1"),
            _make_session("sess-2"),
        ]
        mock_state.get_all_sessions.return_value = sessions

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            display_session_table()

        text = output.getvalue()
        assert "2 sessions" in text
        assert "0 active" in text
        assert "2 inactive" in text


class TestShowSessionInfo:
    """Tests for show_session_info() with backend info."""

    @patch("ccmux.display.get_branch_name", return_value="feature-branch")
    def test_shows_claude_backend(self, mock_branch):
        session = _make_session("test-sess", backend_name="claude", is_worktree=True)

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            show_session_info("test-sess", session)

        text = output.getvalue()
        assert "Backend" in text
        assert "Claude Code" in text
        assert "test-sess" in text
        assert "worktree" in text

    @patch("ccmux.display.get_branch_name", return_value="main")
    def test_shows_opencode_backend(self, mock_branch):
        session = _make_session("oc-sess", backend_name="opencode", is_worktree=False)

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            show_session_info("oc-sess", session)

        text = output.getvalue()
        assert "Backend" in text
        assert "OpenCode" in text
        assert "main repo" in text

    @patch("ccmux.display.get_branch_name", return_value="HEAD")
    def test_shows_detached_branch(self, mock_branch):
        session = _make_session("det-sess", backend_name="claude")

        output = StringIO()
        with patch("ccmux.display.console", _test_console(output)):
            show_session_info("det-sess", session)

        text = output.getvalue()
        assert "(detached)" in text
