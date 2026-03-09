"""Tests for --shallow worktree session functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ccmux import state
from ccmux.exceptions import InvalidArgumentError
from ccmux.state import store as state_store
from ccmux.state.session import Session, WorktreeSession


@pytest.fixture
def temp_state_dir(monkeypatch):
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        monkeypatch.setattr(state_store, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state_store, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


# --- Session dataclass round-trip ---

class TestSessionShallowRoundTrip:
    def test_to_dict_includes_is_shallow_when_true(self):
        sess = WorktreeSession(
            name="test",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/test",
            is_shallow=True,
        )
        d = sess.to_dict()
        assert d["is_shallow"] is True

    def test_to_dict_omits_is_shallow_when_false(self):
        sess = WorktreeSession(
            name="test",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/test",
            is_shallow=False,
        )
        d = sess.to_dict()
        assert "is_shallow" not in d

    def test_from_dict_reads_is_shallow_true(self):
        sess = Session.from_dict("test", {
            "repo_path": "/repo",
            "session_path": "/repo/.ccmux/worktrees/test",
            "is_worktree": True,
            "is_shallow": True,
        })
        assert sess.is_shallow is True

    def test_from_dict_defaults_is_shallow_false(self):
        sess = Session.from_dict("test", {
            "repo_path": "/repo",
            "session_path": "/repo/.ccmux/worktrees/test",
            "is_worktree": True,
        })
        assert sess.is_shallow is False


# --- State store round-trip ---

class TestStoreShallow:
    def test_add_session_with_is_shallow(self, temp_state_dir):
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
            is_shallow=True,
        )
        loaded = state_store._load_raw()
        assert loaded["sessions"]["fox"]["is_shallow"] is True

    def test_add_session_without_is_shallow(self, temp_state_dir):
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
        )
        loaded = state_store._load_raw()
        assert "is_shallow" not in loaded["sessions"]["fox"]

    def test_update_session_clears_shallow(self, temp_state_dir):
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
            is_shallow=True,
        )
        state.update_session("fox", is_shallow=False)
        sess = state.get_session("fox")
        assert sess.is_shallow is False


# --- do_session_new --shallow flag ---

class TestDoSessionNewShallow:
    @patch("ccmux.session_ops.auto_attach_if_outside_tmux")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops._reactivate_orphaned_sessions")
    @patch("ccmux.session_ops._save_new_session_state")
    @patch("ccmux.session_ops._create_new_session_window", return_value=("@1", "@2"))
    @patch("ccmux.session_ops.build_claude_command", return_value="claude")
    @patch("ccmux.session_ops.tmux_session_exists", return_value=False)
    @patch("ccmux.session_ops._print_creation_info")
    @patch("ccmux.session_ops._generate_session_name", return_value="test-session")
    @patch("ccmux.session_ops._resolve_session_type", return_value=True)
    @patch("ccmux.session_ops._validate_repo_context")
    @patch("ccmux.session_ops._setup_worktree")
    def test_shallow_flag_passed_to_setup_worktree(
        self,
        mock_setup_wt,
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
        tmp_path,
    ):
        mock_validate.return_value = (tmp_path, "main", tmp_path)
        (tmp_path / ".ccmux_worktrees").mkdir()

        from ccmux.session_ops import do_session_new
        do_session_new(worktree=True, shallow=True)

        mock_setup_wt.assert_called_once()
        _, kwargs = mock_setup_wt.call_args
        assert kwargs.get("shallow") is True

    @patch("ccmux.session_ops.auto_attach_if_outside_tmux")
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops._reactivate_orphaned_sessions")
    @patch("ccmux.session_ops._save_new_session_state")
    @patch("ccmux.session_ops._create_new_session_window", return_value=("@1", "@2"))
    @patch("ccmux.session_ops.build_claude_command", return_value="claude")
    @patch("ccmux.session_ops.tmux_session_exists", return_value=False)
    @patch("ccmux.session_ops._print_creation_info")
    @patch("ccmux.session_ops._generate_session_name", return_value="test-session")
    @patch("ccmux.session_ops._resolve_session_type", return_value=True)
    @patch("ccmux.session_ops._validate_repo_context")
    @patch("ccmux.session_ops._setup_worktree")
    def test_shallow_flag_saved_in_state(
        self,
        mock_setup_wt,
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
        tmp_path,
    ):
        mock_validate.return_value = (tmp_path, "main", tmp_path)
        (tmp_path / ".ccmux_worktrees").mkdir()

        from ccmux.session_ops import do_session_new
        do_session_new(worktree=True, shallow=True)

        mock_save_state.assert_called_once()
        _, kwargs = mock_save_state.call_args
        assert kwargs.get("is_shallow") is True


# --- do_session_init ---

class TestDoSessionInit:
    @patch("ccmux.session_ops.notify_sidebars")
    @patch("ccmux.session_ops._run_post_create_with_display")
    def test_init_runs_hooks_and_clears_shallow(
        self, mock_run_hooks, mock_notify, temp_state_dir,
    ):
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
            is_worktree=True,
            is_shallow=True,
        )

        from ccmux.session_ops import do_session_init
        do_session_init(name="fox")

        mock_run_hooks.assert_called_once_with(
            Path("/repo"), Path("/repo/.ccmux/worktrees/fox"), "fox",
        )
        sess = state.get_session("fox")
        assert sess.is_shallow is False
        mock_notify.assert_called_once()

    def test_init_rejects_non_worktree(self, temp_state_dir):
        state.add_session(
            session_name="main",
            repo_path="/repo",
            session_path="/repo",
            is_worktree=False,
        )

        from ccmux.session_ops import do_session_init
        with pytest.raises(InvalidArgumentError, match="not a worktree"):
            do_session_init(name="main")

    def test_init_rejects_non_shallow(self, temp_state_dir):
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
            is_worktree=True,
            is_shallow=False,
        )

        from ccmux.session_ops import do_session_init
        with pytest.raises(InvalidArgumentError, match="not shallow"):
            do_session_init(name="fox")
