"""Tests for apply_inner_session_config in ccmux.ui.tmux.config."""

import subprocess
from unittest import mock

from ccmux.ui.tmux.config import apply_inner_session_config


class TestApplyInnerSessionConfig:
    """Tests for apply_inner_session_config()."""

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_returns_true_on_success(self, mock_wait, mock_run):
        """Returns True when all tmux set-option calls succeed."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        assert apply_inner_session_config("ccmux-inner") is True

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_returns_false_on_failure(self, mock_wait, mock_run):
        """Returns False when a tmux set-option call raises CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
        assert apply_inner_session_config("ccmux-inner") is False

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_sets_session_options(self, mock_wait, mock_run):
        """Verifies expected session options are set."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        apply_inner_session_config("ccmux-inner")

        cmds = [call[0][0] for call in mock_run.call_args_list]

        # Session-scoped options (set-option -t)
        expected_session_opts = [
            "mouse",
            "status",
            "set-titles",
            "set-titles-string",
            "window-size",
            "visual-activity",
            "visual-bell",
            "activity-action",
            "bell-action",
        ]
        for opt in expected_session_opts:
            matching = [c for c in cmds if "set-option" in c and opt in c and "-t" in c]
            assert matching, f"Expected set-option for '{opt}'"

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_sets_window_options(self, mock_wait, mock_run):
        """Verifies window options are set with -w flag."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        apply_inner_session_config("ccmux-inner")

        cmds = [call[0][0] for call in mock_run.call_args_list]
        window_cmds = [c for c in cmds if "-w" in c]
        assert len(window_cmds) >= 1
        # monitor-activity should be a window option
        assert any("monitor-activity" in c for c in window_cmds)

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_waits_for_session_first(self, mock_wait, mock_run):
        """Ensures _wait_for_session is called before setting options."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        apply_inner_session_config("my-session")
        mock_wait.assert_called_once_with("my-session")

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    @mock.patch("ccmux.ui.tmux.config._wait_for_session", return_value=True)
    def test_targets_correct_session(self, mock_wait, mock_run):
        """All set-option calls target the correct session name."""
        mock_run.return_value = mock.MagicMock(returncode=0)
        apply_inner_session_config("test-session")

        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert "test-session" in cmd, f"Session name missing from: {cmd}"
