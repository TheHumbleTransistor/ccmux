"""Tests for dependency installation checks (tmux, Claude Code)."""

from unittest import mock

from ccmux.tmux_ops import check_tmux_installed
from ccmux.cli import check_claude_installed


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


def test_check_claude_installed_returns_true_when_found():
    with mock.patch("ccmux.cli.shutil.which", return_value="/usr/local/bin/claude"):
        assert check_claude_installed() is True


def test_check_claude_installed_returns_false_when_missing():
    with mock.patch("ccmux.cli.shutil.which", return_value=None):
        assert check_claude_installed() is False


def test_cli_exits_when_claude_missing():
    """CLI should exit with code 1 when Claude Code is missing (tmux present)."""
    from ccmux.cli import main

    with mock.patch("ccmux.tmux_ops.shutil.which", return_value="/usr/bin/tmux"):
        with mock.patch("ccmux.cli.shutil.which", return_value=None):
            with mock.patch("sys.exit", side_effect=SystemExit(1)) as mock_exit:
                try:
                    main()
                except SystemExit:
                    pass
                mock_exit.assert_called_once_with(1)
