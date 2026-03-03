"""Tests for dependency installation checks (tmux, backends)."""

from unittest import mock

from ccmux.tmux_ops import check_tmux_installed
from ccmux.cli import check_backend_installed
from ccmux.backend import ClaudeCodeBackend, OpenCodeBackend


def test_check_tmux_installed_returns_true_when_found():
    with mock.patch("ccmux.tmux_ops.shutil.which", return_value="/usr/bin/tmux"):
        assert check_tmux_installed() is True


def test_check_tmux_installed_returns_false_when_missing():
    with mock.patch("ccmux.tmux_ops.shutil.which", return_value=None):
        assert check_tmux_installed() is False


def test_cli_exits_when_tmux_missing():
    """CLI should exit with code 1 and a helpful message when tmux is missing."""
    from ccmux.cli import main

    with mock.patch("ccmux.tmux_ops.shutil.which", return_value=None):
        with mock.patch("sys.exit", side_effect=SystemExit(1)) as mock_exit:
            try:
                main()
            except SystemExit:
                pass
            mock_exit.assert_called_once_with(1)


def test_check_backend_installed_returns_true_when_claude_found():
    with mock.patch.object(ClaudeCodeBackend, "check_installed", return_value=True):
        assert check_backend_installed() is True


def test_check_backend_installed_returns_true_when_opencode_found():
    with mock.patch.object(ClaudeCodeBackend, "check_installed", return_value=False):
        with mock.patch.object(OpenCodeBackend, "check_installed", return_value=True):
            assert check_backend_installed() is True


def test_check_backend_installed_returns_false_when_none_found():
    with mock.patch.object(ClaudeCodeBackend, "check_installed", return_value=False):
        with mock.patch.object(OpenCodeBackend, "check_installed", return_value=False):
            assert check_backend_installed() is False


def test_cli_exits_when_no_backend_installed():
    """CLI should exit with code 1 when no backend is installed (tmux present)."""
    from ccmux.cli import main

    with mock.patch("ccmux.tmux_ops.shutil.which", return_value="/usr/bin/tmux"):
        with mock.patch.object(
            ClaudeCodeBackend, "check_installed", return_value=False
        ):
            with mock.patch.object(
                OpenCodeBackend, "check_installed", return_value=False
            ):
                with mock.patch("sys.exit", side_effect=SystemExit(1)) as mock_exit:
                    try:
                        main()
                    except SystemExit:
                        pass
                    mock_exit.assert_called_once_with(1)
