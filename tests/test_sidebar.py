"""Tests for ccmux sidebar and CLI sidebar helpers."""

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ccmux import state
from ccmux.ui import (
    SidebarApp,
    NonInteractiveStatic,
    InstanceRow,
    RepoHeader,
    write_pid_file,
    remove_pid_file,
    SIDEBAR_PIDS_DIR,
)


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
        import ccmux.ui.sidebar.process_id as pid_mod
        import ccmux.cli as cli_mod
        monkeypatch.setattr(pid_mod, "SIDEBAR_PIDS_DIR", tmpdir_path)
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


class TestInnerSessionName:
    """Tests for _inner_session_name and _ccmux_session_from_tmux."""

    def test_inner_session_name(self):
        """_inner_session_name appends '-inner' suffix."""
        from ccmux.cli import _inner_session_name

        assert _inner_session_name("default") == "default-inner"
        assert _inner_session_name("my-session") == "my-session-inner"

    def test_ccmux_session_from_tmux_strips_inner(self):
        """_ccmux_session_from_tmux strips '-inner' suffix."""
        from ccmux.cli import _ccmux_session_from_tmux

        assert _ccmux_session_from_tmux("default-inner") == "default"
        assert _ccmux_session_from_tmux("my-session-inner") == "my-session"

    def test_ccmux_session_from_tmux_no_suffix(self):
        """_ccmux_session_from_tmux returns name unchanged if no '-inner' suffix."""
        from ccmux.cli import _ccmux_session_from_tmux

        assert _ccmux_session_from_tmux("default") == "default"
        assert _ccmux_session_from_tmux("my-session") == "my-session"


class TestIsInstanceWindowActive:
    """Tests for is_instance_window_active wrapper."""

    @mock.patch("ccmux.cli.is_window_active_in_session")
    def test_delegates_to_inner_session(self, mock_active):
        """is_instance_window_active checks the inner session."""
        from ccmux.cli import is_instance_window_active

        mock_active.return_value = True
        result = is_instance_window_active("my-session", "@5")

        assert result is True
        mock_active.assert_called_once_with("my-session-inner", "@5")

    @mock.patch("ccmux.cli.is_window_active_in_session")
    def test_returns_false_for_none_window(self, mock_active):
        """is_instance_window_active handles None window ID."""
        from ccmux.cli import is_instance_window_active

        mock_active.return_value = False
        result = is_instance_window_active("my-session", None)

        assert result is False
        mock_active.assert_called_once_with("my-session-inner", None)


class TestCreateOuterSession:
    """Tests for _create_outer_session CLI helper."""

    @mock.patch("ccmux.cli._install_inner_hook")
    @mock.patch("ccmux.cli.apply_outer_session_config")
    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_creates_outer_with_sidebar_inner_and_bash(
        self, mock_exists, mock_run, mock_outer_config, mock_hook
    ):
        """_create_outer_session creates outer session with sidebar, inner client, and bash pane."""
        from ccmux.cli import _create_outer_session

        # outer doesn't exist, inner and bash do exist
        mock_exists.side_effect = lambda s: s in ("my-session-inner", "my-session-bash")

        _create_outer_session("my-session")

        # Should have called new-session, split-window (bash), split-window (inner)
        assert mock_run.call_count == 3

        # Verify new-session creates the sidebar
        new_session_call = mock_run.call_args_list[0][0][0]
        assert "new-session" in new_session_call
        assert "my-session" in new_session_call
        sidebar_cmd = new_session_call[-1]
        assert "ccmux.ui.sidebar" in sidebar_cmd

        # Verify first split-window creates the bash pane (vertical, bottom)
        bash_split_call = mock_run.call_args_list[1][0][0]
        assert "split-window" in bash_split_call
        assert "-v" in bash_split_call
        assert "20%" in bash_split_call
        bash_cmd = bash_split_call[-1]
        assert "tmux attach -t =my-session-bash" in bash_cmd

        # Verify second split-window creates the inner client (horizontal, right)
        inner_split_call = mock_run.call_args_list[2][0][0]
        assert "split-window" in inner_split_call
        assert "-h" in inner_split_call
        assert "80%" in inner_split_call
        inner_cmd = inner_split_call[-1]
        assert "tmux attach -t =my-session-inner" in inner_cmd

        mock_outer_config.assert_called_once_with("my-session")
        mock_hook.assert_called_once_with("my-session")

    @mock.patch("ccmux.cli._install_inner_hook")
    @mock.patch("ccmux.cli.apply_outer_session_config")
    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_creates_outer_without_bash_session(
        self, mock_exists, mock_run, mock_outer_config, mock_hook
    ):
        """_create_outer_session creates 2-pane layout when bash session doesn't exist."""
        from ccmux.cli import _create_outer_session

        # outer doesn't exist, inner exists, bash doesn't
        mock_exists.side_effect = lambda s: s == "my-session-inner"

        _create_outer_session("my-session")

        # Should have called new-session and split-window (inner only, no bash)
        assert mock_run.call_count == 2

        # Verify new-session creates the sidebar
        new_session_call = mock_run.call_args_list[0][0][0]
        assert "new-session" in new_session_call

        # Verify split-window creates the inner client
        split_call = mock_run.call_args_list[1][0][0]
        assert "split-window" in split_call
        assert "80%" in split_call
        inner_cmd = split_call[-1]
        assert "tmux attach -t =my-session-inner" in inner_cmd

        mock_outer_config.assert_called_once_with("my-session")
        mock_hook.assert_called_once_with("my-session")

    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_skips_if_outer_exists(self, mock_exists, mock_run):
        """_create_outer_session skips if outer session already exists."""
        from ccmux.cli import _create_outer_session

        # Both exist
        mock_exists.return_value = True

        _create_outer_session("my-session")
        mock_run.assert_not_called()

    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_skips_if_inner_missing(self, mock_exists, mock_run):
        """_create_outer_session skips if inner session doesn't exist."""
        from ccmux.cli import _create_outer_session

        # Neither exists
        mock_exists.return_value = False

        _create_outer_session("my-session")
        mock_run.assert_not_called()


class TestKillOuterSession:
    """Tests for _kill_outer_session CLI helper."""

    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists", return_value=True)
    def test_kills_outer_session(self, mock_exists, mock_run):
        """_kill_outer_session kills the outer tmux session."""
        from ccmux.cli import _kill_outer_session

        assert _kill_outer_session("my-session") is True

        kill_call = mock_run.call_args[0][0]
        assert "kill-session" in kill_call
        assert "=my-session" in kill_call

    @mock.patch("ccmux.cli.tmux_session_exists", return_value=False)
    def test_returns_false_when_no_session(self, mock_exists):
        """_kill_outer_session returns False when session doesn't exist."""
        from ccmux.cli import _kill_outer_session

        assert _kill_outer_session("my-session") is False

    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists", return_value=True)
    def test_returns_false_on_kill_failure(self, mock_exists, mock_run):
        """_kill_outer_session returns False if kill-session fails."""
        from ccmux.cli import _kill_outer_session

        mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
        assert _kill_outer_session("my-session") is False


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


class TestReloadSessionSidebar:
    """Tests for _reload_session_sidebar CLI helper."""

    @mock.patch("ccmux.cli.subprocess.run")
    @mock.patch("ccmux.cli.tmux_session_exists", return_value=True)
    def test_kills_pane_and_splits_new(self, mock_exists, mock_run):
        """_reload_session_sidebar kills sidebar pane and splits a new one."""
        from ccmux.cli import _reload_session_sidebar

        _reload_session_sidebar("my-session")

        mock_exists.assert_called_once_with("my-session")
        assert mock_run.call_count == 2
        # First call: kill-pane
        kill_args = mock_run.call_args_list[0]
        assert "kill-pane" in kill_args[0][0]
        # Second call: split-window
        split_args = mock_run.call_args_list[1]
        assert "split-window" in split_args[0][0]

    @mock.patch("ccmux.cli.tmux_session_exists", return_value=False)
    def test_noop_when_no_session(self, mock_exists):
        """_reload_session_sidebar does nothing if outer session doesn't exist."""
        from ccmux.cli import _reload_session_sidebar

        _reload_session_sidebar("my-session")
        mock_exists.assert_called_once_with("my-session")


class TestInstallInnerHook:
    """Tests for _install_inner_hook and _uninstall_inner_hook."""

    @mock.patch("ccmux.cli.subprocess.run")
    def test_creates_hook_script(self, mock_run, tmp_path, monkeypatch):
        """_install_inner_hook writes a script that syncs bash window and notifies sidebars."""
        import ccmux.cli as cli_mod
        monkeypatch.setattr(cli_mod, "HOOKS_DIR", tmp_path)

        from ccmux.cli import _install_inner_hook
        _install_inner_hook("test-session")

        script = tmp_path / "notify-sidebar-test-session.sh"
        assert script.exists()
        content = script.read_text()
        # Should contain bash window switching
        assert "test-session-inner" in content
        assert "test-session-bash" in content
        assert "select-window" in content
        # Should contain SIGUSR1 notification
        assert "sidebar_pids/test-session" in content
        assert "kill -USR1" in content
        # Should NOT contain join-pane (that was the old approach)
        assert "join-pane" not in content

        # Verify tmux set-hook was called on the INNER session
        call_args = mock_run.call_args[0][0]
        assert "set-hook" in call_args
        assert "test-session-inner" in call_args
        assert "after-select-window" in call_args

    @mock.patch("ccmux.cli.subprocess.run")
    def test_uninstall_removes_hook(self, mock_run, tmp_path, monkeypatch):
        """_uninstall_inner_hook removes the hook and script."""
        import ccmux.cli as cli_mod
        monkeypatch.setattr(cli_mod, "HOOKS_DIR", tmp_path)

        # Create a script to remove
        script = tmp_path / "notify-sidebar-test-session.sh"
        script.write_text("#!/bin/sh\n")

        from ccmux.cli import _uninstall_inner_hook
        _uninstall_inner_hook("test-session")

        assert not script.exists()
        call_args = mock_run.call_args[0][0]
        assert "set-hook" in call_args
        assert "-u" in call_args
        # Should target the inner session
        assert "test-session-inner" in call_args


class TestEnsureOuterSession:
    """Tests for _ensure_outer_session CLI helper."""

    @mock.patch("ccmux.cli._install_inner_hook")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_installs_hook_if_outer_exists(self, mock_exists, mock_hook):
        """_ensure_outer_session just installs hook if both sessions exist."""
        from ccmux.cli import _ensure_outer_session

        # Both inner and outer exist
        mock_exists.return_value = True

        _ensure_outer_session("my-session")

        mock_hook.assert_called_once_with("my-session")

    @mock.patch("ccmux.cli._create_outer_session")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_creates_outer_if_missing(self, mock_exists, mock_create):
        """_ensure_outer_session creates outer session if inner exists but outer doesn't."""
        from ccmux.cli import _ensure_outer_session

        # Inner exists, outer doesn't
        mock_exists.side_effect = lambda s: s == "my-session-inner"

        _ensure_outer_session("my-session")

        mock_create.assert_called_once_with("my-session")

    @mock.patch("ccmux.cli._create_outer_session")
    @mock.patch("ccmux.cli.tmux_session_exists")
    def test_returns_early_if_inner_missing(self, mock_exists, mock_create):
        """_ensure_outer_session returns early if inner session doesn't exist."""
        from ccmux.cli import _ensure_outer_session

        # Neither exists
        mock_exists.return_value = False

        _ensure_outer_session("my-session")

        mock_create.assert_not_called()


class TestSidebarRendering:
    """Headless pilot tests verifying widget integrity after simulated clicks."""

    @pytest.fixture
    def demo_app(self):
        """Create a demo SidebarApp for headless testing."""
        return SidebarApp(session="test-demo", demo=True)

    @pytest.mark.asyncio
    async def test_widgets_present_after_instance_click(self, demo_app):
        """Click InstanceRow, verify title/header/instances still mounted and displayed."""
        async with demo_app.run_test() as pilot:
            # Verify initial state — title, header, and instances are present
            app = pilot.app
            title = app.query_one("#title", NonInteractiveStatic)
            header = app.query_one("#header", NonInteractiveStatic)
            assert title.display is True
            assert header.display is True

            # Find and click an InstanceRow
            rows = app.query(InstanceRow)
            assert len(rows) > 0
            await pilot.click(InstanceRow)

            # After click, all structural widgets must still be mounted and visible
            title = app.query_one("#title", NonInteractiveStatic)
            header = app.query_one("#header", NonInteractiveStatic)
            assert title.display is True
            assert header.display is True
            assert len(app.query(InstanceRow)) > 0

    @pytest.mark.asyncio
    async def test_widgets_present_after_header_click(self, demo_app):
        """Click title/RepoHeader, verify no corruption."""
        async with demo_app.run_test() as pilot:
            app = pilot.app

            # Click the title
            await pilot.click("#title")

            title = app.query_one("#title", NonInteractiveStatic)
            header = app.query_one("#header", NonInteractiveStatic)
            assert title.display is True
            assert header.display is True

            # Click a RepoHeader
            repo_headers = app.query(RepoHeader)
            if len(repo_headers) > 0:
                await pilot.click(RepoHeader)
                # Verify everything still intact
                assert app.query_one("#title", NonInteractiveStatic).display is True
                assert app.query_one("#header", NonInteractiveStatic).display is True
                assert len(app.query(InstanceRow)) > 0

    @pytest.mark.asyncio
    async def test_screen_content_after_multiple_clicks(self, demo_app):
        """Rapid-fire clicks on all rows, verify content intact."""
        async with demo_app.run_test() as pilot:
            app = pilot.app

            # Click title, header, then each InstanceRow
            await pilot.click("#title")
            await pilot.click("#header")

            rows = app.query(InstanceRow)
            for row in rows:
                await pilot.click(f"#{row.id}")

            # All structural widgets must survive rapid clicking
            assert app.query_one("#title", NonInteractiveStatic).display is True
            assert app.query_one("#header", NonInteractiveStatic).display is True
            assert app.query_one("#instance-list") is not None
            assert len(app.query(InstanceRow)) > 0

    @pytest.mark.asyncio
    async def test_allow_select_disabled(self, demo_app):
        """Confirm ALLOW_SELECT is False on SidebarApp."""
        assert SidebarApp.ALLOW_SELECT is False
        async with demo_app.run_test() as pilot:
            assert pilot.app.ALLOW_SELECT is False
