"""Tests for ccmux.session_ops session creation helpers."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ccmux.exceptions import (
    DefaultBranchError,
    InvalidArgumentError,
    NotInCcmuxSessionError,
    SessionNotFoundError,
    TmuxError,
    UserAbortedError,
    WorktreeError,
)
from ccmux.naming import BASH_SESSION, INNER_SESSION, OUTER_SESSION
from ccmux.session_ops import (
    _is_running_in_bash_pane,
    _remove_single_session,
    _resolve_session_type,
    _validate_repo_context,
    do_reload,
    do_session_new,
    do_session_reset,
)
from ccmux.state.session import MainRepoSession, WorktreeSession


class TestValidateRepoContext:
    """Tests for _validate_repo_context()."""

    @patch("ccmux.session_ops.get_worktree_root", return_value=None)
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_no_path_returns_repo_root_as_working_dir(
        self, mock_chdir, mock_root, mock_branch, mock_bare, mock_wt_root,
    ):
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


def _make_worktree_session(tmp_path, name="duck", note=None):
    """Build a real WorktreeSession backed by a temp directory that exists."""
    wt = tmp_path / name
    wt.mkdir()
    return WorktreeSession(
        name=name, repo_path=str(tmp_path),
        session_path=str(wt), note=note,
    )


class TestDoSessionReset:
    """Tests for do_session_reset()."""

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    def test_clean_worktree_happy_path(
        self, mock_state, mock_resolve, mock_status, mock_fetch, mock_checkout,
        mock_notify, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name="duck")

        mock_fetch.assert_called_once_with(Path(session.session_path))
        mock_checkout.assert_called_once_with(Path(session.session_path), "origin/main")
        # No note set → update_session should not be called
        mock_state.update_session.assert_not_called()
        mock_notify.assert_called_once()

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    def test_clears_note_when_set(
        self, mock_state, mock_resolve, mock_status, mock_fetch, mock_checkout,
        mock_notify, tmp_path,
    ):
        session = _make_worktree_session(tmp_path, note="some note")
        mock_state.get_session.return_value = session

        do_session_reset(name="duck")

        mock_state.update_session.assert_called_once_with("duck", note="")

    @patch("ccmux.session_ops.discard_all_changes")
    @patch("ccmux.session_ops.stash_changes")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=["M foo.py"])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    @patch("ccmux.session_ops.Prompt.ask", return_value="s")
    def test_dirty_stash_path(
        self, mock_prompt, mock_state, mock_resolve, mock_status, mock_fetch,
        mock_checkout, mock_notify, mock_stash, mock_discard, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name="duck")

        mock_stash.assert_called_once()
        mock_discard.assert_not_called()
        mock_checkout.assert_called_once()

    @patch("ccmux.session_ops.discard_all_changes")
    @patch("ccmux.session_ops.stash_changes")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=["M foo.py", "?? new.py"])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    @patch("ccmux.session_ops.Prompt.ask", return_value="d")
    def test_dirty_discard_path(
        self, mock_prompt, mock_state, mock_resolve, mock_status, mock_fetch,
        mock_checkout, mock_notify, mock_stash, mock_discard, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name="duck")

        mock_discard.assert_called_once()
        mock_stash.assert_not_called()
        mock_checkout.assert_called_once()

    @patch("ccmux.session_ops.discard_all_changes")
    @patch("ccmux.session_ops.stash_changes")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=["M foo.py"])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    @patch("ccmux.session_ops.Prompt.ask", return_value="c")
    def test_dirty_cancel_path(
        self, mock_prompt, mock_state, mock_resolve, mock_status, mock_fetch,
        mock_checkout, mock_stash, mock_discard, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name="duck")

        mock_stash.assert_not_called()
        mock_discard.assert_not_called()
        mock_fetch.assert_not_called()
        mock_checkout.assert_not_called()

    @patch("ccmux.session_ops.discard_all_changes")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=["M foo.py"])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    def test_yes_flag_discards_without_prompt(
        self, mock_state, mock_resolve, mock_status, mock_fetch, mock_checkout,
        mock_notify, mock_discard, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name="duck", yes=True)

        mock_discard.assert_called_once()
        mock_checkout.assert_called_once()

    @patch("ccmux.session_ops.state")
    def test_main_repo_session_rejected(self, mock_state, tmp_path):
        session = MainRepoSession(
            name="main", repo_path=str(tmp_path), session_path=str(tmp_path),
        )
        mock_state.get_session.return_value = session

        with pytest.raises(InvalidArgumentError, match="main repository"):
            do_session_reset(name="main")

    @patch("ccmux.session_ops.state")
    def test_missing_worktree_path_raises(self, mock_state, tmp_path):
        wt = tmp_path / "gone"  # never created
        session = WorktreeSession(
            name="gone", repo_path=str(tmp_path), session_path=str(wt),
        )
        mock_state.get_session.return_value = session

        with pytest.raises(WorktreeError, match="worktree path missing"):
            do_session_reset(name="gone")

    @patch("ccmux.session_ops.state")
    def test_session_not_found_raises(self, mock_state):
        mock_state.get_session.return_value = None
        with pytest.raises(SessionNotFoundError):
            do_session_reset(name="missing")

    @patch("ccmux.session_ops.detect_current_ccmux_session_any", return_value=None)
    def test_no_name_no_detection_raises(self, mock_detect):
        with pytest.raises(NotInCcmuxSessionError):
            do_session_reset(name=None)

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.checkout_detached")
    @patch("ccmux.session_ops.fetch_origin")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    @patch("ccmux.session_ops._resolve_reset_target_ref", return_value="origin/main")
    @patch("ccmux.session_ops.state")
    @patch("ccmux.session_ops.detect_current_ccmux_session_any",
           return_value=("duck", None))
    def test_auto_detect_session_name(
        self, mock_detect, mock_state, mock_resolve, mock_status, mock_fetch,
        mock_checkout, mock_notify, tmp_path,
    ):
        session = _make_worktree_session(tmp_path)
        mock_state.get_session.return_value = session

        do_session_reset(name=None)

        mock_detect.assert_called_once()
        mock_state.get_session.assert_called_with("duck")
        mock_checkout.assert_called_once()


# ---------------------------------------------------------------------------
# Fix 1: Bare repo root detection
# ---------------------------------------------------------------------------

class TestBareRepoWorktreeCreation:
    """Tests for _resolve_session_type with bare repos."""

    @patch("ccmux.session_ops.is_bare_repo", return_value=True)
    @patch("ccmux.session_ops.state.get_all_sessions", return_value=[])
    def test_bare_repo_root_returns_worktree(self, mock_sessions, mock_bare):
        """At bare repo root, _resolve_session_type returns True (create worktree)."""
        result = _resolve_session_type(
            Path("/bare-repo"), worktree=False, yes=False,
            working_dir=Path("/bare-repo"),
        )
        assert result is True

    @patch("ccmux.session_ops.get_worktree_root", return_value=None)
    @patch("ccmux.session_ops.is_bare_repo", return_value=True)
    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/bare-repo"))
    @patch("os.chdir")
    def test_validate_context_bare_root_sets_working_dir(
        self, mock_chdir, mock_root, mock_branch, mock_bare, mock_wt_root,
    ):
        """At bare repo root, _validate_repo_context sets working_dir = repo_root."""
        with patch("ccmux.session_ops.Path") as MockPath:
            MockPath.cwd.return_value.resolve.return_value = Path("/bare-repo")
            # Path(path) shouldn't be called since path is None
            repo_root, branch, working_dir = _validate_repo_context()
        assert working_dir == Path("/bare-repo")
        assert repo_root == Path("/bare-repo")


# ---------------------------------------------------------------------------
# Fix 2: Detect existing session at worktree root
# ---------------------------------------------------------------------------

class TestSessionDetectionAtWorktreeRoot:
    """Tests for detecting existing sessions when running from worktree root."""

    @patch("ccmux.session_ops.get_worktree_root")
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_nonbare_worktree_preserves_worktree_root(
        self, mock_chdir, mock_root, mock_branch, mock_bare, mock_wt_root,
    ):
        """When cwd is inside a linked worktree, working_dir is the worktree root."""
        wt_path = Path("/repo/.ccmux/worktrees/otter")
        mock_wt_root.return_value = wt_path

        with patch("ccmux.session_ops.Path") as MockPath:
            MockPath.cwd.return_value.resolve.return_value = wt_path
            repo_root, branch, working_dir = _validate_repo_context()

        assert working_dir == wt_path

    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_at_repo_root_working_dir_is_repo_root(
        self, mock_chdir, mock_root, mock_branch, mock_bare,
    ):
        """When cwd == repo_root, working_dir equals repo_root (no worktree check)."""
        with patch("ccmux.session_ops.Path") as MockPath:
            MockPath.cwd.return_value.resolve.return_value = Path("/repo")
            repo_root, branch, working_dir = _validate_repo_context()

        assert working_dir == Path("/repo")

    @patch("ccmux.session_ops.get_worktree_root", return_value=Path("/repo"))
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    @patch("ccmux.session_ops.get_default_branch", return_value="main")
    @patch("ccmux.session_ops.get_repo_root", return_value=Path("/repo"))
    @patch("os.chdir")
    def test_subdirectory_of_main_repo_uses_repo_root(
        self, mock_chdir, mock_root, mock_branch, mock_bare, mock_wt_root,
    ):
        """When inside a subdirectory of the main repo, working_dir is repo_root."""
        with patch("ccmux.session_ops.Path") as MockPath:
            MockPath.cwd.return_value.resolve.return_value = Path("/repo/src")
            repo_root, branch, working_dir = _validate_repo_context()

        assert working_dir == Path("/repo")

    @patch("ccmux.session_ops.state.get_all_sessions")
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    def test_resolve_type_detects_worktree_duplicate(self, mock_bare, mock_sessions):
        """Detects existing worktree session and returns True (create new worktree)."""
        mock_session = MagicMock()
        mock_session.session_path = "/repo/.ccmux/worktrees/otter"
        mock_sessions.return_value = [mock_session]

        result = _resolve_session_type(
            Path("/repo"), worktree=False, yes=True,
            working_dir=Path("/repo/.ccmux/worktrees/otter"),
        )
        assert result is True

    @patch("ccmux.session_ops.state.find_main_repo_session", return_value=None)
    @patch("ccmux.session_ops.state.get_all_sessions", return_value=[])
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    def test_resolve_type_no_duplicate_reuses_worktree(
        self, mock_bare, mock_sessions, mock_main,
    ):
        """No existing session at worktree — returns False (reuse directly)."""
        result = _resolve_session_type(
            Path("/repo"), worktree=False, yes=False,
            working_dir=Path("/repo/.ccmux/worktrees/otter"),
        )
        assert result is False

    @patch("ccmux.session_ops.state.get_all_sessions")
    @patch("ccmux.session_ops.is_bare_repo", return_value=False)
    def test_resolve_type_duplicate_user_declines_raises(self, mock_bare, mock_sessions):
        """User declining worktree creation raises UserAbortedError."""
        mock_session = MagicMock()
        mock_session.session_path = "/repo/.ccmux/worktrees/otter"
        mock_sessions.return_value = [mock_session]

        with patch("ccmux.session_ops.Confirm.ask", return_value=False):
            with pytest.raises(UserAbortedError):
                _resolve_session_type(
                    Path("/repo"), worktree=False, yes=False,
                    working_dir=Path("/repo/.ccmux/worktrees/otter"),
                )


# ---------------------------------------------------------------------------
# Fix 3: Remove from bash pane
# ---------------------------------------------------------------------------

class TestIsRunningInBashPane:
    """Tests for _is_running_in_bash_pane()."""

    @patch("ccmux.session_ops.get_current_tmux_session", return_value=BASH_SESSION)
    @patch.dict("os.environ", {"CCMUX_SESSION": "otter"})
    def test_returns_true_when_in_bash_pane(self, mock_tmux):
        assert _is_running_in_bash_pane("otter") is True

    @patch("ccmux.session_ops.get_current_tmux_session", return_value=BASH_SESSION)
    @patch.dict("os.environ", {"CCMUX_SESSION": "fox"})
    def test_returns_false_for_different_session(self, mock_tmux):
        assert _is_running_in_bash_pane("otter") is False

    @patch("ccmux.session_ops.get_current_tmux_session", return_value=INNER_SESSION)
    @patch.dict("os.environ", {"CCMUX_SESSION": "otter"})
    def test_returns_false_when_in_inner_session(self, mock_tmux):
        assert _is_running_in_bash_pane("otter") is False

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_false_when_no_env_var(self):
        assert _is_running_in_bash_pane("otter") is False


class TestRemoveSingleSessionFromBashPane:
    """Tests for _remove_single_session when running from bash pane."""

    def _make_session(self, name="otter"):
        sess = MagicMock()
        sess.name = name
        sess.is_worktree = True
        sess.session_path = f"/repo/.ccmux/worktrees/{name}"
        sess.tmux_cc_window_id = "@1"
        sess.tmux_bash_window_id = "@2"
        return sess

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.state.get_all_sessions", return_value=[])
    @patch("ccmux.session_ops.state.remove_session")
    @patch("ccmux.session_ops._delete_session_worktree")
    @patch("ccmux.session_ops.kill_tmux_session", return_value=True)
    @patch("ccmux.session_ops.kill_tmux_window", return_value=True)
    @patch("ccmux.session_ops.uninstall_inner_hook")
    @patch("ccmux.session_ops._is_running_in_bash_pane", return_value=True)
    @patch("ccmux.session_ops.partition_sessions_by_active")
    @patch("ccmux.session_ops.find_session_by_name")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    def test_last_session_from_bash_kills_bash_session_last(
        self, mock_wt_status, mock_find, mock_partition, mock_in_bash,
        mock_uninstall, mock_kill_window, mock_kill_session,
        mock_delete_wt, mock_remove_state, mock_remaining, mock_notify,
    ):
        """When removing last session from bash pane, BASH_SESSION is killed last."""
        session = self._make_session()
        mock_find.return_value = session
        mock_partition.return_value = ([session], [])

        _remove_single_session("otter", [session], yes=True)

        # CC window killed first (not bash window)
        mock_kill_window.assert_called_once_with("@1")
        # notify_sidebars was called (before any session kill)
        mock_notify.assert_called_once()
        # uninstall_inner_hook was called
        mock_uninstall.assert_called_once()
        # Sessions killed in correct order: OUTER, INNER, BASH
        calls = [c[0][0] for c in mock_kill_session.call_args_list]
        assert calls == [OUTER_SESSION, INNER_SESSION, BASH_SESSION]

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.state.get_all_sessions")
    @patch("ccmux.session_ops.state.remove_session")
    @patch("ccmux.session_ops._delete_session_worktree")
    @patch("ccmux.session_ops.kill_tmux_window", return_value=True)
    @patch("ccmux.session_ops._is_running_in_bash_pane", return_value=True)
    @patch("ccmux.session_ops.partition_sessions_by_active")
    @patch("ccmux.session_ops.find_session_by_name")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    def test_non_last_session_from_bash_kills_own_bash_last(
        self, mock_wt_status, mock_find, mock_partition, mock_in_bash,
        mock_kill_window, mock_delete_wt, mock_remove_state,
        mock_remaining, mock_notify,
    ):
        """When removing non-last session from bash, own bash window killed last."""
        session = self._make_session()
        other = self._make_session("fox")
        mock_find.return_value = session
        mock_partition.return_value = ([session], [])
        mock_remaining.return_value = [other]

        _remove_single_session("otter", [session, other], yes=True)

        # CC window killed first, then own bash window last
        calls = [c[0][0] for c in mock_kill_window.call_args_list]
        assert calls[0] == "@1"  # CC window
        assert calls[-1] == "@2"  # bash window (last)
        mock_notify.assert_called_once()

    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops.state.get_all_sessions", return_value=[])
    @patch("ccmux.session_ops.state.remove_session")
    @patch("ccmux.session_ops._delete_session_worktree")
    @patch("ccmux.session_ops.kill_session_windows", return_value=True)
    @patch("ccmux.session_ops.uninstall_inner_hook")
    @patch("ccmux.session_ops.kill_tmux_session", return_value=True)
    @patch("ccmux.session_ops._is_running_in_bash_pane", return_value=False)
    @patch("ccmux.session_ops.partition_sessions_by_active")
    @patch("ccmux.session_ops.find_session_by_name")
    @patch("ccmux.session_ops.worktree_status", return_value=[])
    def test_not_in_bash_pane_uses_kill_session_windows(
        self, mock_wt_status, mock_find, mock_partition, mock_in_bash,
        mock_kill_session, mock_uninstall, mock_kill_windows,
        mock_delete_wt, mock_remove_state, mock_remaining, mock_notify,
    ):
        """When NOT in bash pane, kill_session_windows is called normally."""
        session = self._make_session()
        mock_find.return_value = session
        mock_partition.return_value = ([session], [])

        _remove_single_session("otter", [session], yes=True)

        mock_kill_windows.assert_called_once_with(
            "otter", "@1", "@2",
        )
