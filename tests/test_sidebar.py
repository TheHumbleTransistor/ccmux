"""Tests for ccmux sidebar and CLI sidebar helpers."""

import json
import os
import signal
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ccmux import state
from ccmux.sidebar import SidebarApp, write_pid_file, remove_pid_file, SIDEBAR_PIDS_DIR


@pytest.fixture
def temp_state_dir(monkeypatch):
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        monkeypatch.setattr(state, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


@pytest.fixture
def temp_pid_dir(monkeypatch):
    """Create a temporary PID directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        import ccmux.sidebar as sidebar_mod
        import ccmux.cli as cli_mod
        monkeypatch.setattr(sidebar_mod, "SIDEBAR_PIDS_DIR", tmpdir_path)
        monkeypatch.setattr(cli_mod, "SIDEBAR_PIDS_DIR", tmpdir_path)
        yield tmpdir_path


class TestSidebarDataHelpers:
    """Tests for sidebar data resolution logic."""

    def test_get_current_instance_by_window_id(self, temp_state_dir):
        """Sidebar identifies current instance by window_id, not name."""
        state.add_worktree(
            session_name="test",
            worktree_name="fox",
            repo_path="/home/user/my-project",
            worktree_path="/home/user/my-project/.worktrees/fox",
            tmux_session_id="$0",
            tmux_window_id="@1",
        )
        state.add_worktree(
            session_name="test",
            worktree_name="bear",
            repo_path="/home/user/my-project",
            worktree_path="/home/user/my-project",
            tmux_session_id="$0",
            tmux_window_id="@2",
            is_worktree=False,
        )

        session_data = state.get_session("test")
        instances = session_data.get("instances", {})

        # Simulate what the sidebar does to find current instance
        window_id = "@1"
        current_name = None
        for inst_name, inst_data in instances.items():
            if inst_data.get("tmux_window_id") == window_id:
                current_name = inst_name
                break

        assert current_name == "fox"

    def test_instances_grouped_by_repo(self, temp_state_dir):
        """Instances should be groupable by repository path."""
        state.add_worktree(
            session_name="test",
            worktree_name="fox",
            repo_path="/home/user/project-a",
            worktree_path="/home/user/project-a/.worktrees/fox",
            tmux_window_id="@1",
        )
        state.add_worktree(
            session_name="test",
            worktree_name="bear",
            repo_path="/home/user/project-a",
            worktree_path="/home/user/project-a",
            tmux_window_id="@2",
            is_worktree=False,
        )
        state.add_worktree(
            session_name="test",
            worktree_name="hawk",
            repo_path="/home/user/project-b",
            worktree_path="/home/user/project-b/.worktrees/hawk",
            tmux_window_id="@3",
        )

        instances = state.get_all_worktrees("test")

        # Group by repo like the sidebar does
        repos: dict[str, list] = {}
        for inst in instances:
            repo_name = Path(inst["repo_path"]).name
            repos.setdefault(repo_name, []).append(inst)

        assert "project-a" in repos
        assert "project-b" in repos
        assert len(repos["project-a"]) == 2
        assert len(repos["project-b"]) == 1

    def test_active_inactive_detection(self, temp_state_dir):
        """Active/inactive detection based on window ID presence."""
        state.add_worktree(
            session_name="test",
            worktree_name="fox",
            repo_path="/repo",
            worktree_path="/repo/.worktrees/fox",
            tmux_window_id="@1",
        )
        state.add_worktree(
            session_name="test",
            worktree_name="bear",
            repo_path="/repo",
            worktree_path="/repo/.worktrees/bear",
            tmux_window_id="@2",
        )

        instances = state.get_all_worktrees("test")
        active_window_ids = {"@1"}  # Simulate: only @1 is in tmux

        for inst in instances:
            is_active = inst.get("tmux_window_id") in active_window_ids
            if inst["name"] == "fox":
                assert is_active
            elif inst["name"] == "bear":
                assert not is_active

    def test_instance_type_detection(self, temp_state_dir):
        """Worktree vs main repo type detection."""
        state.add_worktree(
            session_name="test",
            worktree_name="fox",
            repo_path="/repo",
            worktree_path="/repo/.worktrees/fox",
            tmux_window_id="@1",
            is_worktree=True,
        )
        state.add_worktree(
            session_name="test",
            worktree_name="bear",
            repo_path="/repo",
            worktree_path="/repo",
            tmux_window_id="@2",
            is_worktree=False,
        )

        instances = state.get_all_worktrees("test")
        for inst in instances:
            inst_type = "worktree" if inst.get("is_worktree", True) else "main"
            if inst["name"] == "fox":
                assert inst_type == "worktree"
            elif inst["name"] == "bear":
                assert inst_type == "main"


class TestPidTracking:
    """Tests for PID file management."""

    def test_write_and_remove_pid_file(self, temp_pid_dir):
        """PID file is created and cleaned up correctly."""
        pid_file = write_pid_file("test-session")

        assert pid_file.exists()
        assert pid_file.read_text() == str(os.getpid())
        assert pid_file.parent == temp_pid_dir / "test-session"

        remove_pid_file("test-session")
        assert not pid_file.exists()

    def test_remove_missing_pid_file(self, temp_pid_dir):
        """Removing a non-existent PID file doesn't raise."""
        remove_pid_file("non-existent-session")


class TestAddSidebarPane:
    """Tests for _add_sidebar_pane CLI helper."""

    @mock.patch("ccmux.cli.subprocess.run")
    def test_splits_window_with_correct_args(self, mock_run):
        """_add_sidebar_pane issues correct tmux split-window command."""
        from ccmux.cli import _add_sidebar_pane

        # First call: display-message to get width
        width_result = mock.MagicMock()
        width_result.stdout = "200\n"

        # Second call: split-window
        split_result = mock.MagicMock()

        mock_run.side_effect = [width_result, split_result]

        _add_sidebar_pane("my-session", "@5")

        # Verify width check
        width_call = mock_run.call_args_list[0]
        assert "display-message" in width_call[0][0]
        assert "@5" in width_call[0][0]

        # Verify split-window call
        split_call = mock_run.call_args_list[1]
        split_args = split_call[0][0]
        assert "split-window" in split_args
        assert "-bh" in split_args
        assert "-l" in split_args
        assert "25%" in split_args
        assert "-d" in split_args
        assert "@5" in split_args
        # Verify sidebar command is included
        sidebar_cmd = split_args[-1]
        assert "ccmux.sidebar" in sidebar_cmd
        assert "my-session" in sidebar_cmd
        assert "@5" in sidebar_cmd

    @mock.patch("ccmux.cli.subprocess.run")
    def test_skips_narrow_terminal(self, mock_run):
        """_add_sidebar_pane skips if terminal is too narrow."""
        from ccmux.cli import _add_sidebar_pane

        width_result = mock.MagicMock()
        width_result.stdout = "50\n"
        mock_run.return_value = width_result

        _add_sidebar_pane("my-session", "@5")

        # Only the width check should have been called
        assert mock_run.call_count == 1


class TestNotifySidebars:
    """Tests for _notify_sidebars CLI helper."""

    @mock.patch("ccmux.cli.os.kill")
    def test_sends_sigusr1_to_active_pids(self, mock_kill, temp_pid_dir):
        """_notify_sidebars sends SIGUSR1 to all PIDs in session dir."""
        from ccmux.cli import _notify_sidebars

        # Create PID files
        pid_dir = temp_pid_dir / "test-session"
        pid_dir.mkdir(parents=True)
        (pid_dir / "1234.pid").write_text("1234")
        (pid_dir / "5678.pid").write_text("5678")

        _notify_sidebars("test-session")

        calls = mock_kill.call_args_list
        pids_signaled = {c[0][0] for c in calls}
        assert pids_signaled == {1234, 5678}
        for call in calls:
            assert call[0][1] == signal.SIGUSR1

    @mock.patch("ccmux.cli.os.kill")
    def test_cleans_stale_pid_files(self, mock_kill, temp_pid_dir):
        """_notify_sidebars removes PID files for dead processes."""
        from ccmux.cli import _notify_sidebars

        pid_dir = temp_pid_dir / "test-session"
        pid_dir.mkdir(parents=True)
        stale_pid_file = pid_dir / "9999.pid"
        stale_pid_file.write_text("9999")

        mock_kill.side_effect = ProcessLookupError

        _notify_sidebars("test-session")

        assert not stale_pid_file.exists()

    def test_no_pid_dir(self, temp_pid_dir):
        """_notify_sidebars handles missing PID directory gracefully."""
        from ccmux.cli import _notify_sidebars

        # Should not raise
        _notify_sidebars("non-existent-session")
