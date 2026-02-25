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
from ccmux.state import store as state_store
from textual.widgets import Static

from ccmux.ui import (
    SidebarApp,
    AboutPanel,
    SessionRow,
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
        monkeypatch.setattr(state_store, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state_store, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


@pytest.fixture
def temp_pid_dir(monkeypatch):
    """Create a temporary PID directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        import ccmux.ui.sidebar.process_id as pid_mod
        import ccmux.session_layout as layout_mod
        monkeypatch.setattr(pid_mod, "SIDEBAR_PIDS_DIR", tmpdir_path)
        monkeypatch.setattr(layout_mod, "SIDEBAR_PIDS_DIR", tmpdir_path)
        yield tmpdir_path


class TestSidebarDataHelpers:
    """Tests for sidebar data resolution logic."""

    def test_get_current_session_by_window_id(self, temp_state_dir):
        """Sidebar identifies current session by window_id, not name."""
        state.add_session(
            session_name="fox",
            repo_path="/home/user/my-project",
            session_path="/home/user/my-project/.worktrees/fox",
            tmux_session_id="$0",
            tmux_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/home/user/my-project",
            session_path="/home/user/my-project",
            tmux_session_id="$0",
            tmux_window_id="@2",
            is_worktree=False,
        )

        sessions = state.get_all_sessions()

        # Simulate what the sidebar does to find current session
        window_id = "@1"
        current_name = None
        for sess in sessions:
            if sess.tmux_window_id == window_id:
                current_name = sess.name
                break

        assert current_name == "fox"

    def test_sessions_grouped_by_repo(self, temp_state_dir):
        """Sessions should be groupable by repository path."""
        state.add_session(
            session_name="fox",
            repo_path="/home/user/project-a",
            session_path="/home/user/project-a/.worktrees/fox",
            tmux_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/home/user/project-a",
            session_path="/home/user/project-a",
            tmux_window_id="@2",
            is_worktree=False,
        )
        state.add_session(
            session_name="hawk",
            repo_path="/home/user/project-b",
            session_path="/home/user/project-b/.worktrees/hawk",
            tmux_window_id="@3",
        )

        sessions = state.get_all_sessions()

        # Group by repo like the sidebar does
        repos: dict[str, list] = {}
        for sess in sessions:
            repo_name = Path(sess.repo_path).name
            repos.setdefault(repo_name, []).append(sess)

        assert "project-a" in repos
        assert "project-b" in repos
        assert len(repos["project-a"]) == 2
        assert len(repos["project-b"]) == 1

    def test_active_inactive_detection(self, temp_state_dir):
        """Active/inactive detection based on window ID presence."""
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.worktrees/fox",
            tmux_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/repo",
            session_path="/repo/.worktrees/bear",
            tmux_window_id="@2",
        )

        sessions = state.get_all_sessions()
        active_window_ids = {"@1"}  # Simulate: only @1 is in tmux

        for sess in sessions:
            is_active = sess.tmux_window_id in active_window_ids
            if sess.name == "fox":
                assert is_active
            elif sess.name == "bear":
                assert not is_active

    def test_session_type_detection(self, temp_state_dir):
        """Worktree vs main repo type detection."""
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.worktrees/fox",
            tmux_window_id="@1",
            is_worktree=True,
        )
        state.add_session(
            session_name="bear",
            repo_path="/repo",
            session_path="/repo",
            tmux_window_id="@2",
            is_worktree=False,
        )

        sessions = state.get_all_sessions()
        for sess in sessions:
            if sess.name == "fox":
                assert sess.session_type == "worktree"
            elif sess.name == "bear":
                assert sess.session_type == "main"


class TestPidTracking:
    """Tests for PID file management."""

    def test_write_and_remove_pid_file(self, temp_pid_dir):
        """PID file is created and cleaned up correctly."""
        pid_file = write_pid_file()

        assert pid_file.exists()
        assert pid_file.read_text() == str(os.getpid())
        assert pid_file.parent == temp_pid_dir

        remove_pid_file()
        assert not pid_file.exists()

    def test_remove_missing_pid_file(self, temp_pid_dir):
        """Removing a non-existent PID file doesn't raise."""
        remove_pid_file()


class TestNamingConstants:
    """Tests for naming constants."""

    def test_inner_session_constant(self):
        """INNER_SESSION is ccmux-inner."""
        from ccmux.naming import INNER_SESSION
        assert INNER_SESSION == "ccmux-inner"

    def test_bash_session_constant(self):
        """BASH_SESSION is ccmux-bash."""
        from ccmux.naming import BASH_SESSION
        assert BASH_SESSION == "ccmux-bash"

    def test_outer_session_constant(self):
        """OUTER_SESSION is ccmux."""
        from ccmux.naming import OUTER_SESSION
        assert OUTER_SESSION == "ccmux"


class TestIsSessionWindowActive:
    """Tests for is_session_window_active wrapper."""

    @mock.patch("ccmux.naming.is_window_active_in_session")
    def test_delegates_to_inner_session(self, mock_active):
        """is_session_window_active checks the inner session."""
        from ccmux.naming import is_session_window_active

        mock_active.return_value = True
        result = is_session_window_active("@5")

        assert result is True
        mock_active.assert_called_once_with("ccmux-inner", "@5")

    @mock.patch("ccmux.naming.is_window_active_in_session")
    def test_returns_false_for_none_window(self, mock_active):
        """is_session_window_active handles None window ID."""
        from ccmux.naming import is_session_window_active

        mock_active.return_value = False
        result = is_session_window_active(None)

        assert result is False
        mock_active.assert_called_once_with("ccmux-inner", None)


class TestCreateOuterSession:
    """Tests for create_outer_session helper."""

    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.split_window")
    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_with_sidebar_inner_and_bash(
        self, mock_exists, mock_create_simple, mock_split, mock_server_config, mock_outer_config, mock_hook
    ):
        """create_outer_session creates outer session with sidebar, inner client, and bash pane."""
        from ccmux.session_layout import create_outer_session

        # outer (ccmux) doesn't exist, inner and bash do exist
        mock_exists.side_effect = lambda s: s in ("ccmux-inner", "ccmux-bash")

        create_outer_session()

        # Verify create_session_simple creates the sidebar under outer name
        mock_create_simple.assert_called_once()
        args = mock_create_simple.call_args[0]
        assert args[0] == "ccmux"
        assert "ccmux.ui.sidebar" in args[1]

        # Should have 2 split-window calls (bash + inner)
        assert mock_split.call_count == 2

        # Verify first split creates the bash pane (vertical)
        bash_split = mock_split.call_args_list[0]
        assert bash_split[0][1] == "-v"
        assert "tmux attach -t =ccmux-bash" in bash_split[0][3]

        # Verify second split creates the inner client (horizontal)
        inner_split = mock_split.call_args_list[1]
        assert inner_split[0][1] == "-h"
        assert "tmux attach -t =ccmux-inner" in inner_split[0][3]

        mock_outer_config.assert_called_once_with("ccmux")
        mock_hook.assert_called_once()

    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.split_window")
    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_without_bash_session(
        self, mock_exists, mock_create_simple, mock_split, mock_server_config, mock_outer_config, mock_hook
    ):
        """create_outer_session creates 2-pane layout when bash session doesn't exist."""
        from ccmux.session_layout import create_outer_session

        # outer doesn't exist, inner exists, bash doesn't
        mock_exists.side_effect = lambda s: s == "ccmux-inner"

        create_outer_session()

        mock_create_simple.assert_called_once()

        # Should have 1 split-window call (inner only, no bash)
        assert mock_split.call_count == 1
        inner_split = mock_split.call_args_list[0]
        assert inner_split[0][1] == "-h"
        assert "tmux attach -t =ccmux-inner" in inner_split[0][3]

        mock_outer_config.assert_called_once_with("ccmux")
        mock_hook.assert_called_once()

    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_skips_if_outer_exists(self, mock_exists, mock_create_simple):
        """create_outer_session skips if outer session already exists."""
        from ccmux.session_layout import create_outer_session

        # Both exist
        mock_exists.return_value = True

        create_outer_session()
        mock_create_simple.assert_not_called()

    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_skips_if_inner_missing(self, mock_exists, mock_create_simple):
        """create_outer_session skips if inner session doesn't exist."""
        from ccmux.session_layout import create_outer_session

        # Neither exists
        mock_exists.return_value = False

        create_outer_session()
        mock_create_simple.assert_not_called()


class TestKillOuterSession:
    """Tests for kill_outer_session helper."""

    @mock.patch("ccmux.session_layout.kill_tmux_session", return_value=True)
    def test_kills_outer_session(self, mock_kill):
        """kill_outer_session kills the outer and bash tmux sessions."""
        from ccmux.session_layout import kill_outer_session

        assert kill_outer_session() is True

        calls = [c[0][0] for c in mock_kill.call_args_list]
        assert "ccmux-bash" in calls
        assert "ccmux" in calls

    @mock.patch("ccmux.session_layout.kill_tmux_session", return_value=False)
    def test_returns_false_when_no_session(self, mock_kill):
        """kill_outer_session returns False when session doesn't exist."""
        from ccmux.session_layout import kill_outer_session

        assert kill_outer_session() is False

    @mock.patch("ccmux.session_layout.kill_tmux_session", return_value=False)
    def test_returns_false_on_kill_failure(self, mock_kill):
        """kill_outer_session returns False if kill-session fails."""
        from ccmux.session_layout import kill_outer_session

        assert kill_outer_session() is False


class TestNotifySidebars:
    """Tests for notify_sidebars helper."""

    @mock.patch("ccmux.session_layout.os.kill")
    def test_sends_sigusr1_to_active_pids(self, mock_kill, temp_pid_dir):
        """notify_sidebars sends SIGUSR1 to all PIDs in directory."""
        from ccmux.session_layout import notify_sidebars

        # Create PID files directly in the PID dir (no session subdir)
        (temp_pid_dir / "1234.pid").write_text("1234")
        (temp_pid_dir / "5678.pid").write_text("5678")

        notify_sidebars()

        calls = mock_kill.call_args_list
        pids_signaled = {c[0][0] for c in calls}
        assert pids_signaled == {1234, 5678}
        for call in calls:
            assert call[0][1] == signal.SIGUSR1

    @mock.patch("ccmux.session_layout.os.kill")
    def test_cleans_stale_pid_files(self, mock_kill, temp_pid_dir):
        """notify_sidebars removes PID files for dead processes."""
        from ccmux.session_layout import notify_sidebars

        stale_pid_file = temp_pid_dir / "9999.pid"
        stale_pid_file.write_text("9999")

        mock_kill.side_effect = ProcessLookupError

        notify_sidebars()

        assert not stale_pid_file.exists()

    def test_no_pid_dir(self, temp_pid_dir):
        """notify_sidebars handles missing PID directory gracefully."""
        from ccmux.session_layout import notify_sidebars
        import ccmux.session_layout as layout_mod

        # Point to a non-existent dir
        layout_mod.SIDEBAR_PIDS_DIR = temp_pid_dir / "non-existent"

        # Should not raise
        notify_sidebars()


class TestInstallInnerHook:
    """Tests for install_inner_hook and uninstall_inner_hook."""

    @mock.patch("ccmux.session_layout.set_hook")
    def test_creates_hook_script(self, mock_set_hook, tmp_path, monkeypatch):
        """install_inner_hook writes a script that syncs bash window and notifies sidebars."""
        import ccmux.session_layout as layout_mod
        monkeypatch.setattr(layout_mod, "HOOKS_DIR", tmp_path)

        from ccmux.session_layout import install_inner_hook
        install_inner_hook()

        script = tmp_path / "notify-sidebar.sh"
        assert script.exists()
        content = script.read_text()
        # Should contain bash window switching
        assert "ccmux-inner" in content
        assert "ccmux-bash" in content
        assert "select-window" in content
        # Should contain SIGUSR1 notification
        assert "sidebar_pids" in content
        assert "kill -USR1" in content
        # Should NOT contain join-pane (that was the old approach)
        assert "join-pane" not in content

        # Verify set_hook was called on the INNER session
        assert mock_set_hook.call_count == 2

        # Verify both hooks target the correct window via #{window_id}
        bell_call = mock_set_hook.call_args_list[0]
        assert bell_call[0][0] == "ccmux-inner"
        assert bell_call[0][1] == "alert-bell"
        assert "-t '#{window_id}'" in bell_call[0][2]

        select_call = mock_set_hook.call_args_list[1]
        assert select_call[0][0] == "ccmux-inner"
        assert select_call[0][1] == "after-select-window"
        assert "-t '#{window_id}'" in select_call[0][2]

    @mock.patch("ccmux.session_layout.unset_hook")
    def test_uninstall_removes_hook(self, mock_unset_hook, tmp_path, monkeypatch):
        """uninstall_inner_hook removes the hook and script."""
        import ccmux.session_layout as layout_mod
        monkeypatch.setattr(layout_mod, "HOOKS_DIR", tmp_path)

        # Create a script to remove
        script = tmp_path / "notify-sidebar.sh"
        script.write_text("#!/bin/sh\n")

        from ccmux.session_layout import uninstall_inner_hook
        uninstall_inner_hook()

        assert not script.exists()
        # Verify unset_hook was called for both hooks on the inner session
        assert mock_unset_hook.call_count == 2
        targets = [c[0][0] for c in mock_unset_hook.call_args_list]
        hooks = [c[0][1] for c in mock_unset_hook.call_args_list]
        assert all(t == "ccmux-inner" for t in targets)
        assert "alert-bell" in hooks
        assert "after-select-window" in hooks


class TestEnsureOuterSession:
    """Tests for ensure_outer_session helper."""

    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_installs_hook_if_outer_exists(self, mock_exists, mock_hook):
        """ensure_outer_session just installs hook if both sessions exist."""
        from ccmux.session_layout import ensure_outer_session

        # Both inner and outer exist
        mock_exists.return_value = True

        ensure_outer_session()

        mock_hook.assert_called_once()

    @mock.patch("ccmux.session_layout.create_outer_session")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_if_missing(self, mock_exists, mock_create):
        """ensure_outer_session creates outer session if inner exists but outer doesn't."""
        from ccmux.session_layout import ensure_outer_session

        # Inner exists, outer doesn't
        mock_exists.side_effect = lambda s: s == "ccmux-inner"

        ensure_outer_session()

        mock_create.assert_called_once()

    @mock.patch("ccmux.session_layout.create_outer_session")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_returns_early_if_inner_missing(self, mock_exists, mock_create):
        """ensure_outer_session returns early if inner session doesn't exist."""
        from ccmux.session_layout import ensure_outer_session

        # Neither exists
        mock_exists.return_value = False

        ensure_outer_session()

        mock_create.assert_not_called()


class TestSidebarRendering:
    """Headless pilot tests verifying widget integrity after simulated clicks."""

    @pytest.fixture
    def demo_app(self):
        """Create a demo SidebarApp for headless testing."""
        from tests.demo_sidebar import make_demo_provider

        return SidebarApp(
            snapshot_fn=make_demo_provider(),
            poll_interval=1.0,
        )

    @pytest.mark.asyncio
    async def test_widgets_present_after_session_click(self, demo_app):
        """Click SessionRow, verify title and sessions still mounted and displayed."""
        async with demo_app.run_test() as pilot:
            # Verify initial state — title and sessions are present
            app = pilot.app
            title = app.query_one("#title")
            assert title.display is True

            # Find and click a SessionRow
            rows = app.query(SessionRow)
            assert len(rows) > 0
            await pilot.click(SessionRow)

            # After click, all structural widgets must still be mounted and visible
            title = app.query_one("#title")
            assert title.display is True
            assert len(app.query(SessionRow)) > 0

    @pytest.mark.asyncio
    async def test_widgets_present_after_header_click(self, demo_app):
        """Click title/RepoHeader, verify no corruption."""
        async with demo_app.run_test() as pilot:
            app = pilot.app

            # Click the title — now toggles about panel on
            await pilot.click("#title")
            # Click again to toggle back to session list
            await pilot.click("#title")

            title = app.query_one("#title")
            assert title.display is True

            # Click a RepoHeader
            repo_headers = app.query(RepoHeader)
            if len(repo_headers) > 0:
                await pilot.click(RepoHeader)
                # Verify everything still intact
                assert app.query_one("#title").display is True
                assert len(app.query(SessionRow)) > 0

    @pytest.mark.asyncio
    async def test_screen_content_after_multiple_clicks(self, demo_app):
        """Rapid-fire clicks on all rows, verify content intact."""
        async with demo_app.run_test(size=(80, 40)) as pilot:
            app = pilot.app

            # Click title twice (toggle about on then off), then each SessionRow
            await pilot.click("#title")
            await pilot.click("#title")

            rows = app.query(SessionRow)
            for row in rows:
                await pilot.click(f"#{row.id}")

            # All structural widgets must survive rapid clicking
            assert app.query_one("#title").display is True
            assert app.query_one("#instance-list") is not None
            assert len(app.query(SessionRow)) > 0

    @pytest.mark.asyncio
    async def test_allow_select_disabled(self, demo_app):
        """Confirm ALLOW_SELECT is False on SidebarApp."""
        assert SidebarApp.ALLOW_SELECT is False
        async with demo_app.run_test() as pilot:
            assert pilot.app.ALLOW_SELECT is False


class TestAboutPanel:
    """Tests for the about/info panel toggled via the title banner."""

    @pytest.fixture
    def demo_app(self):
        from tests.demo_sidebar import make_demo_provider

        return SidebarApp(
            snapshot_fn=make_demo_provider(),
            poll_interval=1.0,
        )

    @pytest.mark.asyncio
    async def test_about_panel_hidden_by_default(self, demo_app):
        """About panel should be mounted but not displayed initially."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            about = app.query_one("#about-panel")
            assert about.display is False
            assert app.query_one("#instance-list").display is True

    @pytest.mark.asyncio
    async def test_title_click_shows_about(self, demo_app):
        """Clicking title shows about panel and hides session list."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            await pilot.click("#title")

            assert app.query_one("#about-panel").display is True
            assert app.query_one("#instance-list").display is False

    @pytest.mark.asyncio
    async def test_title_click_toggles_back(self, demo_app):
        """Clicking title again hides about panel and shows sessions."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            await pilot.click("#title")
            await pilot.click("#title")

            assert app.query_one("#about-panel").display is False
            assert app.query_one("#instance-list").display is True

    @pytest.mark.asyncio
    async def test_escape_closes_about(self, demo_app):
        """Pressing Escape closes the about panel."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            await pilot.click("#title")
            assert app.query_one("#about-panel").display is True

            await pilot.press("escape")
            assert app.query_one("#about-panel").display is False
            assert app.query_one("#instance-list").display is True

    @pytest.mark.asyncio
    async def test_escape_noop_when_about_not_shown(self, demo_app):
        """Pressing Escape when about panel is hidden does nothing."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            await pilot.press("escape")

            # Session list still visible, about still hidden
            assert app.query_one("#about-panel").display is False
            assert app.query_one("#instance-list").display is True

    @pytest.mark.asyncio
    async def test_about_panel_contains_version(self, demo_app):
        """About panel should contain the version string."""
        from ccmux import __version__
        from ccmux.ui.sidebar.widgets.about_panel import ABOUT_TEXT

        assert __version__ in ABOUT_TEXT

    @pytest.mark.asyncio
    async def test_back_button_closes_about(self, demo_app):
        """Clicking the back button in the about panel closes it."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            await pilot.click("#title")
            assert app.query_one("#about-panel").display is True

            await pilot.click("#about-back")
            assert app.query_one("#about-panel").display is False
            assert app.query_one("#instance-list").display is True

    @pytest.mark.asyncio
    async def test_sessions_survive_about_toggle(self, demo_app):
        """Sessions remain mounted after toggling about panel on and off."""
        async with demo_app.run_test() as pilot:
            app = pilot.app
            rows_before = len(app.query(SessionRow))
            assert rows_before > 0

            # Toggle on, then off
            await pilot.click("#title")
            await pilot.click("#title")

            rows_after = len(app.query(SessionRow))
            assert rows_after == rows_before
