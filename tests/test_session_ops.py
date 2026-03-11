"""Tests for ccmux.session_ops session creation helpers."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ccmux.exceptions import InvalidArgumentError, TmuxError
from ccmux.naming import OUTER_SESSION
from ccmux.session_ops import _validate_repo_context, do_reload, do_session_new


class TestValidateRepoContext:
    """Tests for _validate_repo_context()."""

    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_no_path_returns_repo_root_as_working_dir(self, mock_chdir, mock_root, mock_branch):
        """When no path is given, working_dir equals repo_root."""
        repo_root, default_branch, working_dir = _validate_repo_context()
        assert working_dir == repo_root
        assert repo_root == Path("/repo")
        assert default_branch == "main"

    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_with_subdirectory_returns_resolved_path(self, mock_chdir, mock_root, mock_branch, tmp_path):
        """When a subdirectory path is given, working_dir is that resolved path."""
        subdir = tmp_path / "subproject"
        subdir.mkdir()

        repo_root, default_branch, working_dir = _validate_repo_context(str(subdir))
        assert working_dir == subdir
        assert repo_root == Path("/repo")

    def test_nonexistent_path_raises(self):
        """Raises InvalidArgumentError for a path that does not exist."""
        with pytest.raises(InvalidArgumentError, match="not a directory"):
            _validate_repo_context("/no/such/path")


class TestDoSessionNewUsesWorkingDir:
    """Tests for do_session_new() — non-worktree path handling."""

    @patch("ccmux.session_ops.auto_attach_if_outside_tmux")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops._reactivate_orphaned_sessions")
    @patch("ccmux.session_ops._save_new_session_state")
    @patch("ccmux.session_ops._create_new_session_window", return_value=("@1", "@2"))
    @patch("ccmux.session_ops.build_agent_command", return_value="claude")
    @patch("ccmux.session_ops.tmux_session_exists", return_value=False)
    @patch("ccmux.session_ops._print_creation_info")
    @patch("ccmux.session_ops._generate_session_name", return_value="test-session")
    @patch("ccmux.session_ops._resolve_session_type", return_value=False)
    @patch("ccmux.session_ops._validate_repo_context")
    def test_non_worktree_session_uses_working_dir(
        self,
        mock_validate,
        mock_resolve_type,
        mock_gen_name,
        mock_print_info,
        mock_tmux_exists,
        mock_build_cmd,
        mock_create_window,
        mock_save_state,
        mock_reactivate,
        mock_notify,
        mock_auto_attach,
    ):
        """Non-worktree session uses working_dir (not repo_root) as session_path."""
        repo_root = Path("/repo")
        working_dir = Path("/repo/sub/dir")
        mock_validate.return_value = (repo_root, "main", working_dir)

        do_session_new(path="/repo/sub/dir")

        # session_path passed to _create_new_session_window should be working_dir
        mock_create_window.assert_called_once()
        call_args = mock_create_window.call_args
        assert call_args[0][1] == str(working_dir)

        # session_path passed to _save_new_session_state should be working_dir
        mock_save_state.assert_called_once()
        save_args = mock_save_state.call_args
        assert save_args[0][2] == working_dir


class TestDoReload:
    """Tests for do_reload()."""

    @patch("ccmux.session_ops.tmux_session_exists", return_value=False)
    def test_no_inner_session_raises(self, mock_exists):
        """Raises TmuxError when inner session is not running."""
        with pytest.raises(TmuxError, match="No active workspace"):
            do_reload()

    @patch.dict("os.environ", {}, clear=False)
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.create_outer_session")
    @patch("ccmux.session_ops.kill_tmux_session", return_value=True)
    @patch("ccmux.session_ops.tmux_session_exists")
    def test_kills_outer_and_recreates(
        self, mock_exists, mock_kill, mock_create, mock_notify,
    ):
        """Normal reload: kills outer, recreates, notifies sidebars."""
        mock_exists.side_effect = [True, True]  # inner exists, outer exists after create
        do_reload()
        mock_kill.assert_called_once_with(OUTER_SESSION)
        mock_create.assert_called_once()
        mock_notify.assert_called_once()

    @patch.dict("os.environ", {}, clear=False)
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.create_outer_session")
    @patch("ccmux.session_ops.kill_tmux_session", return_value=False)
    @patch("ccmux.session_ops.tmux_session_exists")
    def test_outer_already_dead(
        self, mock_exists, mock_kill, mock_create, mock_notify,
    ):
        """Reload works even if outer session was already dead."""
        mock_exists.side_effect = [True, True]
        do_reload()
        mock_create.assert_called_once()

    @patch("ccmux.session_ops.create_outer_session")
    @patch("ccmux.session_ops.kill_tmux_session", return_value=True)
    @patch("ccmux.session_ops.tmux_session_exists")
    def test_create_fails_raises(self, mock_exists, mock_kill, mock_create):
        """Raises TmuxError if outer session cannot be recreated."""
        mock_exists.side_effect = [True, False]  # inner exists, outer absent after create
        with pytest.raises(TmuxError, match="Failed to recreate"):
            do_reload()
