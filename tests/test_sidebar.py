"""Tests for ccmux sidebar and CLI sidebar helpers."""

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from textual import events

from ccmux import state
from ccmux.state import store as state_store
from ccmux.session_layout import reload_outer_session
from ccmux.ui.sidebar import sidebar_app as sidebar_app_module
from ccmux.ui.sidebar import snapshot as snapshot_module
from ccmux.ui.sidebar.snapshot import SessionSnapshot, aggregate_status, order_groups
from textual.widgets import Checkbox, Input, OptionList, Static

from ccmux.ui import (
    SidebarApp,
    AboutPanel,
    SessionRow,
    RepoHeader,
    RepoSessionsList,
    NewSessionPanel,
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
            session_path="/home/user/my-project/.ccmux/worktrees/fox",
            tmux_session_id="$0",
            tmux_cc_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/home/user/my-project",
            session_path="/home/user/my-project",
            tmux_session_id="$0",
            tmux_cc_window_id="@2",
            is_worktree=False,
        )

        sessions = state.get_all_sessions()

        # Simulate what the sidebar does to find current session
        window_id = "@1"
        current_name = None
        for sess in sessions:
            if sess.tmux_cc_window_id == window_id:
                current_name = sess.name
                break

        assert current_name == "fox"

    def test_sessions_grouped_by_repo(self, temp_state_dir):
        """Sessions should be groupable by repository path."""
        state.add_session(
            session_name="fox",
            repo_path="/home/user/project-a",
            session_path="/home/user/project-a/.ccmux/worktrees/fox",
            tmux_cc_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/home/user/project-a",
            session_path="/home/user/project-a",
            tmux_cc_window_id="@2",
            is_worktree=False,
        )
        state.add_session(
            session_name="hawk",
            repo_path="/home/user/project-b",
            session_path="/home/user/project-b/.ccmux/worktrees/hawk",
            tmux_cc_window_id="@3",
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
            session_path="/repo/.ccmux/worktrees/fox",
            tmux_cc_window_id="@1",
        )
        state.add_session(
            session_name="bear",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/bear",
            tmux_cc_window_id="@2",
        )

        sessions = state.get_all_sessions()
        active_window_ids = {"@1"}  # Simulate: only @1 is in tmux

        for sess in sessions:
            is_active = sess.tmux_cc_window_id in active_window_ids
            if sess.name == "fox":
                assert is_active
            elif sess.name == "bear":
                assert not is_active

    def test_session_type_detection(self, temp_state_dir):
        """Worktree vs main repo type detection."""
        state.add_session(
            session_name="fox",
            repo_path="/repo",
            session_path="/repo/.ccmux/worktrees/fox",
            tmux_cc_window_id="@1",
            is_worktree=True,
        )
        state.add_session(
            session_name="bear",
            repo_path="/repo",
            session_path="/repo",
            tmux_cc_window_id="@2",
            is_worktree=False,
        )

        sessions = state.get_all_sessions()
        for sess in sessions:
            if sess.name == "fox":
                assert sess.session_type == "worktree"
            elif sess.name == "bear":
                assert sess.session_type == "main"


class TestGroupByRepo:
    """Tests for group_by_repo sort order."""

    def test_group_by_repo_sorts_by_id(self):
        """Worktree sessions sort by session_id (creation order), not alphabetically."""
        from ccmux.ui.sidebar.snapshot import SessionSnapshot, DerivedSessionState, group_by_repo

        snapshots = [
            SessionSnapshot("repo", "/fake/repo", "main-sess", "main", True, False, None, session_id=1),
            SessionSnapshot("repo", "/fake/repo", "zebra", "worktree", True, False, None, session_id=2),
            SessionSnapshot("repo", "/fake/repo", "alpha", "worktree", True, False, None, session_id=3),
        ]
        derived = [
            DerivedSessionState(snapshot=s, status="idle", has_blocker_alert=False)
            for s in snapshots
        ]

        grouped = group_by_repo(derived)
        names = [d.snapshot.session_name for d in grouped["/fake/repo"]]
        # main first, then worktrees in creation order (zebra before alpha)
        assert names == ["main-sess", "zebra", "alpha"]


def _mock_grouped(path_to_ids: dict[str, list[int]]) -> dict:
    """Build a grouped dict mapping repo paths to lists of mock DerivedSessionState."""
    from ccmux.ui.sidebar.snapshot import DerivedSessionState, SessionSnapshot

    grouped: dict[str, list] = {}
    for path, ids in path_to_ids.items():
        grouped[path] = [
            DerivedSessionState(
                snapshot=SessionSnapshot(
                    repo_name=path.rsplit("/", 1)[-1],
                    repo_path=path,
                    session_name=f"sess-{sid}",
                    session_type="main",
                    is_active=True,
                    is_current=False,
                    alert_state=None,
                    session_id=sid,
                ),
                status="idle",
                has_blocker_alert=False,
            )
            for sid in ids
        ]
    return grouped


class TestBuildRepoDisplayNames:
    """Tests for build_repo_display_names disambiguation."""

    def test_unique_names_unchanged(self):
        """Unique directory names include trailing slash."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        grouped = _mock_grouped({
            "/home/user/project-a": [1],
            "/home/user/project-b": [2],
        })
        result = build_repo_display_names(grouped)
        assert result == {
            "/home/user/project-a": "project-a/",
            "/home/user/project-b": "project-b/",
        }

    def test_duplicate_names_disambiguated_by_session_id(self):
        """Older repo (lower session ID) keeps clean name; newer gets suffix."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        grouped = _mock_grouped({
            "/home/user/work/my-app": [5],
            "/home/user/projects/my-app": [10],
        })
        result = build_repo_display_names(grouped)
        assert result["/home/user/work/my-app"] == "my-app/"
        assert result["/home/user/projects/my-app"] == "my-app/ (2)"

    def test_three_duplicates_ordered_by_session_id(self):
        """Three paths with the same name — ordered by minimum session ID."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        grouped = _mock_grouped({
            "/z/my-app": [3],
            "/a/my-app": [7],
            "/m/my-app": [1],
        })
        result = build_repo_display_names(grouped)
        # /m has min session_id=1, /z has 3, /a has 7
        assert result["/m/my-app"] == "my-app/"
        assert result["/z/my-app"] == "my-app/ (2)"
        assert result["/a/my-app"] == "my-app/ (3)"

    def test_empty_input(self):
        """Empty input returns empty dict."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        assert build_repo_display_names({}) == {}

    def test_mixed_unique_and_duplicate(self):
        """Mix of unique and duplicate names."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        grouped = _mock_grouped({
            "/a/unique-repo": [5],
            "/b/shared-name": [1],
            "/c/shared-name": [10],
        })
        result = build_repo_display_names(grouped)
        assert result["/a/unique-repo"] == "unique-repo/"
        assert result["/b/shared-name"] == "shared-name/"
        assert result["/c/shared-name"] == "shared-name/ (2)"

    def test_multiple_sessions_uses_minimum_id(self):
        """When a repo has multiple sessions, the minimum session ID determines order."""
        from ccmux.ui.sidebar.snapshot import build_repo_display_names

        grouped = _mock_grouped({
            "/x/my-app": [10, 20],
            "/y/my-app": [5, 30],
        })
        result = build_repo_display_names(grouped)
        # /y has min session_id=5, /x has min session_id=10
        assert result["/y/my-app"] == "my-app/"
        assert result["/x/my-app"] == "my-app/ (2)"


class TestResolveAlertState:
    """Tests for resolve_alert_state priority logic."""

    def test_none_flags(self):
        """None flags → no alert."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        assert resolve_alert_state(None) is None

    def test_empty_flags(self):
        """Empty dict → no alert."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        assert resolve_alert_state({}) is None

    def test_recently_active_only(self):
        """recently_active=True → activity alert."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        flags = {"bell": False, "recently_active": True, "sid": "1"}
        assert resolve_alert_state(flags) == "activity"

    def test_bell_only(self):
        """bell=True → bell alert."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        flags = {"bell": True, "recently_active": False, "sid": "1"}
        assert resolve_alert_state(flags) == "bell"

    def test_bell_and_recently_active(self):
        """Both bell and recently_active → bell wins."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        flags = {"bell": True, "recently_active": True, "sid": "1"}
        assert resolve_alert_state(flags) == "bell"

    def test_neither(self):
        """Neither bell nor recently_active → no alert."""
        from ccmux.ui.sidebar.snapshot import resolve_alert_state
        flags = {"bell": False, "recently_active": False, "sid": "1"}
        assert resolve_alert_state(flags) is None


class TestStickyBlockedState:
    """Tests for the sticky blocked/blocker-alert state machine in SidebarApp."""

    def _make_app(self):
        """Create a SidebarApp with no snapshot function for unit-testing state logic."""
        app = SidebarApp(snapshot_fn=lambda: [], poll_interval=60.0)
        # Initialise sticky sets (normally done in __init__)
        return app

    def _snap(self, name="fox", is_active=True, alert_state=None):
        from ccmux.ui.sidebar.snapshot import SessionSnapshot
        return SessionSnapshot(
            repo_name="repo", repo_path="/fake/repo", session_name=name,
            session_type="worktree",
            is_active=is_active, is_current=False, alert_state=alert_state,
            session_id=1,
        )

    def test_bell_sets_blocked_and_alert(self):
        """Bell event sets both blocked status and blocker alert flag."""
        app = self._make_app()
        status, has_alert = app._compute_session_state(self._snap(alert_state="bell"))
        assert status == "blocked"
        assert has_alert is True

    def test_click_clears_alert_but_not_blocked(self):
        """After bell, clearing blocker_alerted (simulating click) keeps blocked status."""
        app = self._make_app()
        # Bell fires
        app._compute_session_state(self._snap(alert_state="bell"))
        # Simulate click: clear blocker alert only
        app._blocker_alerted_sessions.discard("fox")
        # Next poll with None (tmux bell flag cleared after window select)
        status, has_alert = app._compute_session_state(self._snap(alert_state=None))
        assert status == "blocked"
        assert has_alert is False

    def test_activity_clears_both(self):
        """Activity event clears both blocked status and blocker alert."""
        app = self._make_app()
        # Bell fires
        app._compute_session_state(self._snap(alert_state="bell"))
        assert "fox" in app._blocked_sessions
        assert "fox" in app._blocker_alerted_sessions
        # Activity fires
        status, has_alert = app._compute_session_state(self._snap(alert_state="activity"))
        assert status == "active"
        assert has_alert is False
        assert "fox" not in app._blocked_sessions
        assert "fox" not in app._blocker_alerted_sessions

    def test_deactivation_clears_all(self):
        """Deactivation clears all sticky state."""
        app = self._make_app()
        # Bell fires
        app._compute_session_state(self._snap(alert_state="bell"))
        # Session deactivates
        status, has_alert = app._compute_session_state(self._snap(is_active=False))
        assert status == "deactivated"
        assert has_alert is False
        assert "fox" not in app._blocked_sessions
        assert "fox" not in app._blocker_alerted_sessions

    def test_idle_when_no_sticky_state(self):
        """Active session with no alert and no sticky state → idle."""
        app = self._make_app()
        status, has_alert = app._compute_session_state(self._snap(alert_state=None))
        assert status == "idle"
        assert has_alert is False

    def test_sticky_persists_across_none_polls(self):
        """Blocked status persists when tmux returns None (bell flag cleared)."""
        app = self._make_app()
        # Bell fires
        app._compute_session_state(self._snap(alert_state="bell"))
        # Multiple None polls (tmux cleared the bell flag)
        for _ in range(3):
            status, has_alert = app._compute_session_state(self._snap(alert_state=None))
            assert status == "blocked"


class TestPostSelectionActivityDebounce:
    """Tests for the post-selection debounce that prevents misleading activity from changing status."""

    def _make_app(self):
        app = SidebarApp(snapshot_fn=lambda: [], poll_interval=60.0)
        return app

    def _snap(self, name="fox", is_active=True, alert_state=None, activity_ts=0.0):
        from ccmux.ui.sidebar.snapshot import SessionSnapshot
        return SessionSnapshot(
            repo_name="repo", repo_path="/fake/repo", session_name=name,
            session_type="worktree",
            is_active=is_active, is_current=False, alert_state=alert_state,
            session_id=1, activity_ts=activity_ts,
        )

    def test_post_selection_activity_does_not_clear_blocked(self):
        """Activity from window focus should not clear blocked status after click."""
        import time
        app = self._make_app()
        # Bell fires — session becomes blocked
        app._compute_session_state(self._snap(alert_state="bell"))
        assert "fox" in app._blocked_sessions

        # Simulate clicking the blocked row
        click_time = time.time()
        app._post_selection_debounce["fox"] = click_time

        # Activity arrives with timestamp *before* debounce cutoff (misleading window-focus activity)
        status, has_alert = app._compute_session_state(
            self._snap(alert_state="activity", activity_ts=click_time + 0.1),
        )
        assert status == "blocked"
        assert "fox" in app._blocked_sessions

    def test_real_activity_clears_blocked_after_debounce(self):
        """Activity with timestamp after debounce window should clear blocked status."""
        import time
        app = self._make_app()
        # Bell fires — session becomes blocked
        app._compute_session_state(self._snap(alert_state="bell"))
        assert "fox" in app._blocked_sessions

        # Simulate clicking the blocked row
        click_time = time.time() - 1.0  # click happened 1 second ago
        app._post_selection_debounce["fox"] = click_time

        # Activity arrives with timestamp well after the debounce cutoff
        status, has_alert = app._compute_session_state(
            self._snap(alert_state="activity", activity_ts=click_time + 1.0),
        )
        assert status == "active"
        assert "fox" not in app._blocked_sessions
        # Debounce entry should be cleaned up
        assert "fox" not in app._post_selection_debounce

    def test_activity_without_debounce_clears_normally(self):
        """Activity on a blocked session with no debounce entry clears blocked status normally."""
        app = self._make_app()
        # Bell fires — session becomes blocked
        app._compute_session_state(self._snap(alert_state="bell"))
        assert "fox" in app._blocked_sessions

        # No debounce entry (no click happened) — activity clears normally
        status, has_alert = app._compute_session_state(
            self._snap(alert_state="activity", activity_ts=9999999999.0),
        )
        assert status == "active"
        assert "fox" not in app._blocked_sessions

    def test_activity_without_click_not_debounced(self):
        """Activity on a session with no debounce entry is not affected."""
        app = self._make_app()
        # Session is idle (no click happened) — activity should set active
        status, has_alert = app._compute_session_state(
            self._snap(alert_state="activity", activity_ts=0.0),
        )
        assert status == "active"


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
        mock_active.assert_called_once_with("ccmux-inner", "@5", expected_sid=None)

    @mock.patch("ccmux.naming.is_window_active_in_session")
    def test_returns_false_for_none_window(self, mock_active):
        """is_session_window_active handles None window ID."""
        from ccmux.naming import is_session_window_active

        mock_active.return_value = False
        result = is_session_window_active(None)

        assert result is False
        mock_active.assert_called_once_with("ccmux-inner", None, expected_sid=None)


class TestCreateOuterSession:
    """Tests for create_outer_session helper."""

    @mock.patch("ccmux.session_layout._send_sigwinch_to_pane")
    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.respawn_pane", return_value=True)
    @mock.patch("ccmux.session_layout.resize_pane")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.split_window")
    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_with_sidebar_inner_and_bash(
        self, mock_exists, mock_create_simple, mock_split, mock_server_config,
        mock_outer_config, mock_resize, mock_respawn, mock_hook, mock_sigwinch
    ):
        """create_outer_session creates outer session with sidebar, inner client, and bash pane."""
        from ccmux.session_layout import create_outer_session

        # Track call order across all mocks
        call_log = []
        mock_create_simple.side_effect = lambda *a, **kw: call_log.append("create_session_simple")
        mock_server_config.side_effect = lambda *a, **kw: call_log.append("apply_server_global_config")
        mock_outer_config.side_effect = lambda *a, **kw: call_log.append("apply_outer_session_config")
        mock_split.side_effect = lambda *a, **kw: call_log.append("split_window")
        mock_resize.side_effect = lambda *a, **kw: call_log.append("resize_pane")
        mock_respawn.side_effect = lambda *a, **kw: (call_log.append("respawn_pane"), True)[-1]
        mock_hook.side_effect = lambda *a, **kw: call_log.append("install_inner_hook")

        # outer (ccmux) doesn't exist, inner and bash do exist
        mock_exists.side_effect = lambda s: s in ("ccmux-inner", "ccmux-bash")

        create_outer_session()

        # Verify create_session_simple creates session with placeholder
        mock_create_simple.assert_called_once()
        args = mock_create_simple.call_args[0]
        assert args[0] == "ccmux"
        assert args[1] == "sleep infinity"

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

        # Verify respawn_pane starts the sidebar AFTER layout is stable
        mock_respawn.assert_called_once()
        respawn_args = mock_respawn.call_args[0]
        assert respawn_args[0] == "ccmux:0.0"
        assert "ccmux.ui.sidebar" in respawn_args[1]

        mock_outer_config.assert_called_once_with("ccmux")
        mock_hook.assert_called_once()

        # Verify ordering: config → splits → resize → respawn → hook
        outer_config_idx = call_log.index("apply_outer_session_config")
        first_split_idx = call_log.index("split_window")
        resize_idx = call_log.index("resize_pane")
        respawn_idx = call_log.index("respawn_pane")
        hook_idx = call_log.index("install_inner_hook")
        assert outer_config_idx < first_split_idx, (
            f"apply_outer_session_config (index {outer_config_idx}) must be called "
            f"before split_window (index {first_split_idx}); call order: {call_log}"
        )
        assert resize_idx < respawn_idx, (
            f"resize_pane (index {resize_idx}) must be called "
            f"before respawn_pane (index {respawn_idx}); call order: {call_log}"
        )
        assert respawn_idx < hook_idx, (
            f"respawn_pane (index {respawn_idx}) must be called "
            f"before install_inner_hook (index {hook_idx}); call order: {call_log}"
        )

    @mock.patch("ccmux.session_layout._send_sigwinch_to_pane")
    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.respawn_pane", return_value=True)
    @mock.patch("ccmux.session_layout.resize_pane")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.split_window")
    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_without_bash_session(
        self, mock_exists, mock_create_simple, mock_split, mock_server_config,
        mock_outer_config, mock_resize, mock_respawn, mock_hook, mock_sigwinch
    ):
        """create_outer_session creates 2-pane layout when bash session doesn't exist."""
        from ccmux.session_layout import create_outer_session

        # outer doesn't exist, inner exists, bash doesn't
        mock_exists.side_effect = lambda s: s == "ccmux-inner"

        create_outer_session()

        # Verify placeholder is used, not sidebar command
        mock_create_simple.assert_called_once()
        args = mock_create_simple.call_args[0]
        assert args[1] == "sleep infinity"

        # Should have 1 split-window call (inner only, no bash)
        assert mock_split.call_count == 1
        inner_split = mock_split.call_args_list[0]
        assert inner_split[0][1] == "-h"
        assert "tmux attach -t =ccmux-inner" in inner_split[0][3]

        # Verify respawn_pane starts the sidebar
        mock_respawn.assert_called_once()
        assert "ccmux.ui.sidebar" in mock_respawn.call_args[0][1]

        mock_outer_config.assert_called_once_with("ccmux")
        mock_hook.assert_called_once()

    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.respawn_pane", return_value=False)
    @mock.patch("ccmux.session_layout.resize_pane")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.split_window")
    @mock.patch("ccmux.session_layout.create_session_simple")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_respawn_failure_skips_hook_install(
        self, mock_exists, mock_create_simple, mock_split, mock_server_config,
        mock_outer_config, mock_resize, mock_respawn, mock_hook
    ):
        """create_outer_session returns early without installing hooks when respawn fails."""
        from ccmux.session_layout import create_outer_session

        mock_exists.side_effect = lambda s: s == "ccmux-inner"

        create_outer_session()

        mock_respawn.assert_called_once()
        mock_hook.assert_not_called()

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


class TestApplyServerGlobalConfig:
    """Tests for terminal-features deduplication in apply_server_global_config."""

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    def test_skips_append_when_rgb_already_present(self, mock_run):
        """apply_server_global_config does not append when tmux-256color:RGB exists."""
        from ccmux.ui.tmux.config import apply_server_global_config

        def fake_run(cmd, **kwargs):
            result = mock.MagicMock()
            if cmd[:3] == ["tmux", "show-options", "-g"]:
                result.returncode = 0
                result.stdout = "xterm-256color:clipboard:ccolour:cstyle:focus:overline:RGB:strikethrough:title:usstyle,tmux-256color:RGB"
                return result
            # set-option -g default-terminal
            result.returncode = 0
            return result

        mock_run.side_effect = fake_run

        assert apply_server_global_config() is True

        # Should have called set-option for default-terminal and show-options,
        # but NOT the -as append
        cmds = [call[0][0] for call in mock_run.call_args_list]
        assert ["tmux", "set-option", "-g", "default-terminal", "tmux-256color"] in cmds
        assert ["tmux", "show-options", "-g", "-v", "terminal-features"] in cmds
        assert ["tmux", "set-option", "-s", "focus-events", "on"] in cmds
        # No -as append command
        for cmd in cmds:
            assert "-as" not in cmd, f"Unexpected append command: {cmd}"

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    def test_appends_when_rgb_not_present(self, mock_run):
        """apply_server_global_config appends when tmux-256color:RGB is missing."""
        from ccmux.ui.tmux.config import apply_server_global_config

        def fake_run(cmd, **kwargs):
            result = mock.MagicMock()
            if cmd[:3] == ["tmux", "show-options", "-g"]:
                result.returncode = 0
                result.stdout = "xterm-256color:clipboard"
                return result
            result.returncode = 0
            return result

        mock_run.side_effect = fake_run

        assert apply_server_global_config() is True

        cmds = [call[0][0] for call in mock_run.call_args_list]
        append_cmds = [c for c in cmds if "-as" in c]
        assert len(append_cmds) == 1

    @mock.patch("ccmux.ui.tmux.config.subprocess.run")
    def test_appends_when_show_options_fails(self, mock_run):
        """apply_server_global_config falls back to appending if show-options fails."""
        from ccmux.ui.tmux.config import apply_server_global_config

        def fake_run(cmd, **kwargs):
            result = mock.MagicMock()
            if cmd[:3] == ["tmux", "show-options", "-g"]:
                result.returncode = 1
                result.stdout = ""
                return result
            result.returncode = 0
            return result

        mock_run.side_effect = fake_run

        assert apply_server_global_config() is True

        cmds = [call[0][0] for call in mock_run.call_args_list]
        append_cmds = [c for c in cmds if "-as" in c]
        assert len(append_cmds) == 1


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
        assert mock_set_hook.call_count == 3

        # Verify hooks use run-shell without @ccmux_bell management
        bell_call = mock_set_hook.call_args_list[0]
        assert bell_call[0][0] == "ccmux-inner"
        assert bell_call[0][1] == "alert-bell"
        assert "run-shell" in bell_call[0][2]
        assert "@ccmux_bell" not in bell_call[0][2]

        select_call = mock_set_hook.call_args_list[1]
        assert select_call[0][0] == "ccmux-inner"
        assert select_call[0][1] == "after-select-window"
        assert "run-shell" in select_call[0][2]
        assert "@ccmux_bell" not in select_call[0][2]

        activity_call = mock_set_hook.call_args_list[2]
        assert activity_call[0][0] == "ccmux-inner"
        assert activity_call[0][1] == "alert-activity"
        assert "run-shell" in activity_call[0][2]
        assert "@ccmux_bell" not in activity_call[0][2]

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
        # Verify unset_hook was called for all hooks on the inner session
        assert mock_unset_hook.call_count == 3
        targets = [c[0][0] for c in mock_unset_hook.call_args_list]
        hooks = [c[0][1] for c in mock_unset_hook.call_args_list]
        assert all(t == "ccmux-inner" for t in targets)
        assert "alert-bell" in hooks
        assert "after-select-window" in hooks
        assert "alert-activity" in hooks


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


class TestReloadOuterSession:
    """Tests for reload_outer_session helper."""

    @mock.patch("ccmux.session_layout._send_sigwinch_to_pane")
    @mock.patch("ccmux.session_layout._rebind_detach_key")
    @mock.patch("ccmux.session_layout.install_detach_hook")
    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.respawn_pane", return_value=True)
    @mock.patch("ccmux.session_layout.apply_claude_inner_session_config")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.create_outer_session")
    @mock.patch("ccmux.session_layout.tmux_session_exists", return_value=True)
    def test_reapplies_config_hooks_and_restarts_sidebar(
        self, mock_exists, mock_create, mock_server_config, mock_outer_config,
        mock_inner_config, mock_respawn, mock_inner_hook, mock_detach_hook,
        mock_rebind, mock_sigwinch,
    ):
        """With the outer session running, config and hooks are reapplied and only the sidebar pane restarts."""
        assert reload_outer_session() is True

        mock_create.assert_not_called()
        mock_server_config.assert_called_once()
        mock_outer_config.assert_called_once_with("ccmux")
        mock_inner_config.assert_called_once_with("ccmux-inner")
        mock_inner_hook.assert_called_once()
        mock_detach_hook.assert_called_once()
        mock_rebind.assert_called_once()

        mock_respawn.assert_called_once()
        target, cmd = mock_respawn.call_args[0]
        assert target == "ccmux:0.0"
        assert "ccmux.ui.sidebar" in cmd
        mock_sigwinch.assert_called_once_with("ccmux:0.0")

    @mock.patch("ccmux.session_layout._send_sigwinch_to_pane")
    @mock.patch("ccmux.session_layout.install_inner_hook")
    @mock.patch("ccmux.session_layout.respawn_pane", return_value=False)
    @mock.patch("ccmux.session_layout.apply_claude_inner_session_config")
    @mock.patch("ccmux.session_layout.apply_outer_session_config")
    @mock.patch("ccmux.session_layout.apply_server_global_config")
    @mock.patch("ccmux.session_layout.tmux_session_exists", return_value=True)
    def test_respawn_failure_returns_false(
        self, mock_exists, mock_server_config, mock_outer_config, mock_inner_config,
        mock_respawn, mock_hook, mock_sigwinch,
    ):
        """A failed respawn reports False and skips the resize signal."""
        assert reload_outer_session() is False
        mock_sigwinch.assert_not_called()

    @mock.patch("ccmux.session_layout.respawn_pane")
    @mock.patch("ccmux.session_layout.create_outer_session")
    @mock.patch("ccmux.session_layout.tmux_session_exists")
    def test_creates_outer_when_missing(self, mock_exists, mock_create, mock_respawn):
        """Without an outer session, reload falls back to creating it."""
        mock_exists.side_effect = [False, True]
        assert reload_outer_session() is True
        mock_create.assert_called_once()
        mock_respawn.assert_not_called()

    @mock.patch("ccmux.session_layout.create_outer_session")
    @mock.patch("ccmux.session_layout.tmux_session_exists", return_value=False)
    def test_create_failure_returns_false(self, mock_exists, mock_create):
        """Reload reports False if the outer session could not be created."""
        assert reload_outer_session() is False


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


class TestSessionRowSelected:
    """Tests for SessionRow.Selected message carrying session ID."""

    def test_select_message_includes_session_id(self):
        """SessionRow.Selected carries the session_id from the row."""
        msg = SessionRow.Selected("fox", session_id=3)
        assert msg.session_name == "fox"
        assert msg.session_id == 3

    def test_select_message_session_id_defaults_to_zero(self):
        """SessionRow.Selected defaults session_id to 0."""
        msg = SessionRow.Selected("fox")
        assert msg.session_name == "fox"
        assert msg.session_id == 0

    @pytest.mark.asyncio
    async def test_click_posts_message_with_session_id(self):
        """Clicking a SessionRow posts Selected with the correct session ID."""
        from tests.demo_sidebar import make_demo_provider

        provider = make_demo_provider()
        app = SidebarApp(
            snapshot_fn=provider,
            poll_interval=60.0,
            on_select=lambda name: provider.select(name),
        )
        async with app.run_test() as pilot:
            rows = pilot.app.query(SessionRow)
            assert len(rows) > 0
            first_row = rows[0]
            # Verify the row carries a session ID
            assert first_row.session_id > 0


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


class TestSnapshotOwnershipValidation:
    """Tests for @ccmux_sid ownership validation in snapshot building."""

    @pytest.mark.asyncio
    async def test_snapshot_rejects_wrong_sid(self):
        """Window exists but @ccmux_sid doesn't match → inactive."""
        from ccmux.ui.sidebar.snapshot import SessionSnapshot, resolve_alert_state

        # Simulate: window @9 exists with sid="5" but session has id=3
        window_flags = {
            "@9": {"bell": False, "recently_active": False, "sid": "5"},
        }
        sess_id = 3
        wid = "@9"
        wid_flags = window_flags.get(wid)
        is_active = (
            wid_flags is not None
            and str(sess_id) == wid_flags.get("sid", "")
        )
        assert is_active is False

    @pytest.mark.asyncio
    async def test_snapshot_accepts_correct_sid(self):
        """Window exists and @ccmux_sid matches → active."""
        window_flags = {
            "@9": {"bell": False, "recently_active": True, "sid": "3"},
        }
        sess_id = 3
        wid = "@9"
        wid_flags = window_flags.get(wid)
        is_active = (
            wid_flags is not None
            and str(sess_id) == wid_flags.get("sid", "")
        )
        assert is_active is True


class TestOrderGroups:
    """Tests for order_groups repo group ordering."""

    def test_follows_repo_order(self):
        grouped = _mock_grouped({"/a": [1], "/b": [2], "/c": [3]})
        assert list(order_groups(grouped, ["/c", "/a", "/b"])) == ["/c", "/a", "/b"]

    def test_unlisted_repos_keep_order_at_end(self):
        grouped = _mock_grouped({"/a": [1], "/b": [2], "/c": [3], "/d": [4]})
        assert list(order_groups(grouped, ["/c"])) == ["/c", "/a", "/b", "/d"]

    def test_empty_order_is_identity(self):
        grouped = _mock_grouped({"/b": [1], "/a": [2]})
        assert list(order_groups(grouped, [])) == ["/b", "/a"]

    def test_stale_entries_ignored(self):
        grouped = _mock_grouped({"/a": [1], "/b": [2]})
        assert list(order_groups(grouped, ["/gone", "/b", "/a"])) == ["/b", "/a"]


class _ListProvider:
    """Snapshot provider over a mutable list of (session_name, repo_name) pairs."""

    def __init__(self, entries: list[tuple[str, str]]) -> None:
        self.entries = list(entries)
        self.alerts: dict[str, str | None] = {}

    async def __call__(self):
        return [
            SessionSnapshot(
                repo, f"/fake/{repo}", name, "worktree", True, False,
                self.alerts.get(name), session_id=sid,
            )
            for sid, (name, repo) in enumerate(self.entries, 1)
        ]


def _group_paths(app) -> list[str]:
    return [group.repo_path for group in app.query(RepoSessionsList)]


def _group(app, repo_path: str):
    return next(g for g in app.query(RepoSessionsList) if g.repo_path == repo_path)


class TestAggregateStatus:
    """Tests for aggregate_status priority."""

    def test_blocked_beats_everything(self):
        assert aggregate_status(["idle", "active", "blocked", "deactivated"]) == "blocked"

    def test_active_beats_idle(self):
        assert aggregate_status(["idle", "active", "deactivated"]) == "active"

    def test_idle_beats_deactivated(self):
        assert aggregate_status(["deactivated", "idle"]) == "idle"

    def test_all_deactivated(self):
        assert aggregate_status(["deactivated", "deactivated"]) == "deactivated"

    def test_empty(self):
        assert aggregate_status([]) == "deactivated"


def _toggle_text(group) -> str:
    return str(group.query_one(RepoHeader).query_one(".toggle", Static).content)


def _title_text(group) -> str:
    return str(group.query_one(RepoHeader).query_one(".title", Static).content)


class TestRepoGroupCollapse:
    """Headless pilot tests for collapsing repo groups via the header arrow and arrow keys."""

    @pytest.fixture
    def provider(self):
        return _ListProvider([("fox", "alpha"), ("bear", "alpha"), ("hawk", "beta")])

    @pytest.fixture
    def app(self, provider):
        return SidebarApp(snapshot_fn=provider, poll_interval=60.0, on_select=lambda name: None)

    @pytest.mark.asyncio
    async def test_arrow_click_collapses_without_selecting(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            rows = list(group.query(SessionRow))
            assert len(rows) == 2 and all(row.display for row in rows)

            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()

            assert group.collapsed and group.has_class("collapsed")
            assert not group.selected
            assert not any(row.display for row in rows)
            assert _toggle_text(group) == "▸"
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/ [#666666 not bold](2)[/]"
            assert not _group(pilot.app, "/fake/beta").collapsed

    @pytest.mark.asyncio
    async def test_second_arrow_click_expands(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()
            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()

            assert not group.collapsed
            assert not group.selected
            assert all(row.display for row in group.query(SessionRow))
            assert _toggle_text(group) == "▾"
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/"

    @pytest.mark.asyncio
    async def test_title_click_selects_without_collapsing(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()

            assert group.selected
            assert not group.collapsed
            assert group._blink_timer is not None
            assert pilot.app._selection_timer is not None

    @pytest.mark.asyncio
    async def test_left_right_collapse_and_expand_selected(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()

            await pilot.press("left")
            await pilot.pause()
            assert group.collapsed

            await pilot.press("right")
            await pilot.pause()
            assert not group.collapsed

    @pytest.mark.asyncio
    async def test_collapsed_state_survives_rebuild(self, app, provider):
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.click(_group(pilot.app, "/fake/alpha").query_one(".toggle"))
            await pilot.pause()

            provider.entries.append(("wolf", "beta"))
            await pilot.app._refresh_sessions(caller="test")
            await pilot.pause()

            group = _group(pilot.app, "/fake/alpha")
            assert group.collapsed
            assert not any(row.display for row in group.query(SessionRow))
            assert pilot.app.query_one("#sess-wolf", SessionRow).display

    @pytest.mark.asyncio
    async def test_collapsed_header_reflects_blocker_alert(self, app, provider):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()
            assert not group.has_class("blocker-alert")

            provider.alerts["fox"] = "bell"
            await pilot.app._refresh_sessions(caller="test")
            await pilot.pause()
            assert group.has_class("blocker-alert")
            assert _title_text(group).startswith("[#d70000]●[/] alpha/")

            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()
            assert not group.has_class("blocker-alert")
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/"

    @pytest.mark.asyncio
    async def test_header_dot_reflects_group_status_only_when_collapsed(self, app, provider):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/"

            provider.alerts["fox"] = "activity"
            await pilot.app._refresh_sessions(caller="test")
            await pilot.pause()
            assert group._breath_timer is None
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/"

            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()
            assert group._breath_timer is not None
            assert _title_text(group).startswith("[")
            assert "●[/] alpha/" in _title_text(group)

            provider.alerts["fox"] = "bell"
            await pilot.app._refresh_sessions(caller="test")
            await pilot.pause()
            assert group._breath_timer is None
            assert _title_text(group) == "[#d70000]●[/] alpha/ [#666666 not bold](2)[/]"

            await pilot.click(group.query_one(".toggle"))
            await pilot.pause()
            assert _title_text(group) == "[#9e9e9e]●[/] alpha/"

    @pytest.mark.asyncio
    async def test_selection_times_out(self, app, monkeypatch):
        monkeypatch.setattr(sidebar_app_module, "SELECTION_INACTIVITY_TIMEOUT", 0.8)
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()
            assert group.selected

            await pilot.pause(1.5)
            assert not group.selected
            assert group._blink_timer is None
            assert pilot.app._selection_timer is None

    @pytest.mark.asyncio
    async def test_keyboard_activity_resets_timeout(self, app, monkeypatch):
        monkeypatch.setattr(sidebar_app_module, "SELECTION_INACTIVITY_TIMEOUT", 1.0)
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause(0.5)
            await pilot.press("down")
            await pilot.pause(0.8)
            assert group.selected

            await pilot.pause(1.2)
            assert not group.selected


class TestRepoGroupReorder:
    """Headless pilot tests for reordering repo groups with up/down arrows."""

    @pytest.fixture
    def provider(self):
        return _ListProvider([("fox", "alpha"), ("bear", "beta"), ("hawk", "gamma")])

    @pytest.fixture
    def app(self, provider):
        return SidebarApp(snapshot_fn=provider, poll_interval=60.0, on_select=lambda name: None)

    @pytest.mark.asyncio
    async def test_down_and_up_move_selected_group(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            assert _group_paths(pilot.app) == ["/fake/alpha", "/fake/beta", "/fake/gamma"]
            await pilot.click(_group(pilot.app, "/fake/alpha").query_one(".title"))
            await pilot.pause()

            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/alpha", "/fake/gamma"]

            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/gamma", "/fake/alpha"]

            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/gamma", "/fake/alpha"]

            await pilot.press("up")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/alpha", "/fake/gamma"]
            assert _group(pilot.app, "/fake/alpha").selected

    @pytest.mark.asyncio
    async def test_arrows_without_selection_are_noops(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.press("down")
            await pilot.press("up")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/alpha", "/fake/beta", "/fake/gamma"]

    @pytest.mark.asyncio
    async def test_escape_clears_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()
            assert group.selected

            await pilot.press("escape")
            await pilot.pause()
            assert not group.selected

            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/alpha", "/fake/beta", "/fake/gamma"]

    @pytest.mark.asyncio
    async def test_click_elsewhere_clears_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()
            assert group.selected

            await pilot.click("#sess-hawk")
            await pilot.pause()
            assert not group.selected

    @pytest.mark.asyncio
    async def test_losing_focus_clears_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            group = _group(pilot.app, "/fake/alpha")
            await pilot.click(group.query_one(".title"))
            await pilot.pause()
            assert group.selected

            pilot.app.post_message(events.AppBlur())
            await pilot.pause()
            assert not group.selected
            assert group._blink_timer is None
            assert pilot.app._selection_timer is None

            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/alpha", "/fake/beta", "/fake/gamma"]

    @pytest.mark.asyncio
    async def test_clicking_another_title_moves_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            alpha = _group(pilot.app, "/fake/alpha")
            beta = _group(pilot.app, "/fake/beta")
            await pilot.click(alpha.query_one(".title"))
            await pilot.pause()
            await pilot.click(beta.query_one(".title"))
            await pilot.pause()

            assert beta.selected
            assert not alpha.selected
            assert alpha._blink_timer is None
            assert not alpha.collapsed and not beta.collapsed

    @pytest.mark.asyncio
    async def test_arrow_click_keeps_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            alpha = _group(pilot.app, "/fake/alpha")
            beta = _group(pilot.app, "/fake/beta")
            await pilot.click(alpha.query_one(".title"))
            await pilot.pause()
            await pilot.click(beta.query_one(".toggle"))
            await pilot.pause()

            assert alpha.selected
            assert beta.collapsed and not beta.selected

    @pytest.mark.asyncio
    async def test_order_survives_rebuild(self, app, provider):
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.click(_group(pilot.app, "/fake/alpha").query_one(".title"))
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            provider.entries.append(("wolf", "delta"))
            await pilot.app._refresh_sessions(caller="test")
            await pilot.pause()
            assert _group_paths(pilot.app) == [
                "/fake/beta", "/fake/alpha", "/fake/gamma", "/fake/delta",
            ]


class TestSidebarPrefsPersistence:
    """Collapsed state and group order persist in state.json when persist_prefs is set."""

    @pytest.mark.asyncio
    async def test_prefs_saved_and_restored(self, temp_state_dir):
        provider = _ListProvider([("fox", "alpha"), ("bear", "beta")])
        app = SidebarApp(snapshot_fn=provider, poll_interval=60.0, persist_prefs=True)
        async with app.run_test(size=(80, 60)) as pilot:
            alpha = _group(pilot.app, "/fake/alpha")
            await pilot.click(alpha.query_one(".toggle"))
            await pilot.pause()
            await pilot.click(alpha.query_one(".title"))
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

        assert state.get_sidebar_prefs() == {
            "repo_order": ["/fake/beta", "/fake/alpha"],
            "collapsed_repos": ["/fake/alpha"],
        }

        app2 = SidebarApp(snapshot_fn=provider, poll_interval=60.0, persist_prefs=True)
        async with app2.run_test(size=(80, 60)) as pilot:
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/alpha"]
            assert _group(pilot.app, "/fake/alpha").collapsed
            assert not _group(pilot.app, "/fake/beta").collapsed

    @pytest.mark.asyncio
    async def test_no_persistence_by_default(self, temp_state_dir):
        provider = _ListProvider([("fox", "alpha"), ("bear", "beta")])
        app = SidebarApp(snapshot_fn=provider, poll_interval=60.0)
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.click(_group(pilot.app, "/fake/alpha").query_one(".title"))
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert _group_paths(pilot.app) == ["/fake/beta", "/fake/alpha"]

        assert not (temp_state_dir / "state.json").exists()


class _Runner:
    """Fake ccmux CLI runner that records the arguments it is asked to run."""

    def __init__(self, returncode: int = 0, output: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.output = output

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        return self.returncode, self.output


def _workspace(tmp_path) -> Path:
    ws = tmp_path / "ws"
    for name in ("alpha", "alpine", "beta"):
        (ws / name / ".git").mkdir(parents=True)
    return ws


class TestNewSessionPanel:
    """Headless pilot tests for the "+ new session" panel."""

    @pytest.fixture
    def ws(self, tmp_path):
        return _workspace(tmp_path)

    @pytest.fixture
    def runner(self):
        return _Runner()

    def _make_app(self, ws, runner):
        async def provider():
            return [SessionSnapshot("alpha", str(ws / "alpha"), "fox", "main", True, False, None, session_id=1)]

        return SidebarApp(
            snapshot_fn=provider, poll_interval=60.0, on_select=lambda name: None,
            cli_runner=runner, workspace_dirs_fn=lambda: [ws],
        )

    @pytest.fixture
    def app(self, ws, runner):
        return self._make_app(ws, runner)

    async def _open(self, pilot):
        await pilot.click("#add-button")
        await pilot.pause()

    @pytest.mark.asyncio
    async def test_button_opens_panel_and_back_closes(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            assert pilot.app.query_one("#new-session-panel").display
            assert not pilot.app.query_one("#instance-list").display
            assert not pilot.app.query_one("#add-button").display
            assert pilot.app.query_one(NewSessionPanel).mode is None

            await pilot.click("#new-back")
            await pilot.pause()
            assert not pilot.app.query_one("#new-session-panel").display
            assert pilot.app.query_one("#instance-list").display
            assert pilot.app.query_one("#add-button").display

    @pytest.mark.asyncio
    async def test_existing_repo_filters_and_submits(self, app, runner, ws):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("enter")
            await pilot.pause()
            panel = pilot.app.query_one(NewSessionPanel)
            assert panel.mode == "existing"
            choices = pilot.app.query_one("#new-choices", OptionList)
            assert choices.option_count == 3

            await pilot.press(*"alp")
            await pilot.pause()
            assert choices.option_count == 2

            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert runner.calls == [["new", str(ws / "alpine"), "-y"]]
            assert not pilot.app.query_one("#new-session-panel").display
            assert pilot.app.query_one("#instance-list").display
            assert pilot.app.focused is None

    @pytest.mark.asyncio
    async def test_shallow_checkbox_adds_flag(self, app, runner, ws):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("enter")
            await pilot.pause()
            pilot.app.query_one("#new-shallow", Checkbox).value = True
            await pilot.click("#new-choices")
            await pilot.pause()
            assert runner.calls == [["new", str(ws / "alpha"), "-y", "-s"]]

    @pytest.mark.asyncio
    async def test_typed_path_wins_over_list(self, app, runner, ws):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("enter")
            await pilot.pause()
            pilot.app.query_one("#new-input", Input).value = str(ws / "beta")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert runner.calls == [["new", str(ws / "beta"), "-y"]]

    @pytest.mark.asyncio
    async def test_clone_mode_submits_clone_command(self, app, runner, ws):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("down", "enter")
            await pilot.pause()
            assert pilot.app.query_one(NewSessionPanel).mode == "clone"
            pilot.app.query_one("#new-input", Input).value = "https://x/org/proj.git"
            await pilot.press("enter")
            await pilot.pause()
            assert runner.calls == [["clone", "https://x/org/proj.git", "--into", str(ws), "-y"]]

    @pytest.mark.asyncio
    async def test_new_project_mode_submits_init_command(self, app, runner, ws):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert pilot.app.query_one(NewSessionPanel).mode == "new"
            await pilot.press(*"proj")
            await pilot.press("enter")
            await pilot.pause()
            assert runner.calls == [["new", str(ws / "proj"), "--init", "-y"]]

    @pytest.mark.asyncio
    async def test_failure_shows_error_and_keeps_panel_open(self, ws):
        runner = _Runner(returncode=1, output="Creating...\nError: boom\n")
        app = self._make_app(ws, runner)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert len(runner.calls) == 1
            panel = pilot.app.query_one(NewSessionPanel)
            assert pilot.app.query_one("#new-session-panel").display
            assert not panel.busy
            assert "Error: boom" in str(pilot.app.query_one("#new-status", Static).content)

    @pytest.mark.asyncio
    async def test_escape_steps_back_then_closes(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            await self._open(pilot)
            await pilot.press("enter")
            await pilot.pause()
            panel = pilot.app.query_one(NewSessionPanel)
            assert panel.mode == "existing"

            await pilot.press("escape")
            await pilot.pause()
            assert panel.mode is None
            assert pilot.app.query_one("#new-session-panel").display

            await pilot.press("escape")
            await pilot.pause()
            assert not pilot.app.query_one("#new-session-panel").display
            assert pilot.app.query_one("#instance-list").display

    @pytest.mark.asyncio
    async def test_about_panel_hides_button(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            await pilot.click("#title")
            await pilot.pause()
            assert not pilot.app.query_one("#add-button").display
            await pilot.click("#title")
            await pilot.pause()
            assert pilot.app.query_one("#add-button").display


class TestCountUncommittedChanges:
    @mock.patch("ccmux.ui.sidebar.snapshot.subprocess.run")
    def test_counts_status_lines(self, mock_run):
        mock_run.return_value = mock.Mock(stdout=" M a.py\n?? new.txt\n\n")
        assert snapshot_module.count_uncommitted_changes("/repo/wt") == 2
        assert mock_run.call_args[0][0] == ["git", "-C", "/repo/wt", "status", "--porcelain"]

    @mock.patch("ccmux.ui.sidebar.snapshot.subprocess.run", side_effect=subprocess.CalledProcessError(128, "git"))
    def test_failure_is_none(self, mock_run):
        assert snapshot_module.count_uncommitted_changes("/nope") is None


class TestSessionRemoval:
    """Pilot tests for the trash icons on a selected repo group's session rows."""

    @pytest.fixture
    def runner(self):
        return _Runner()

    def _make_app(self, runner):
        async def provider():
            return [
                SessionSnapshot("alpha", "/fake/alpha", "fox", "main", True, False, None,
                                session_id=1, session_path="/fake/alpha"),
                SessionSnapshot("alpha", "/fake/alpha", "bear", "worktree", True, False, None,
                                session_id=2, session_path="/fake/alpha/.ccmux/worktrees/bear"),
                SessionSnapshot("beta", "/fake/beta", "hawk", "worktree", True, False, None,
                                session_id=3, session_path="/fake/beta/.ccmux/worktrees/hawk"),
            ]

        return SidebarApp(snapshot_fn=provider, poll_interval=60.0, on_select=lambda name: None, cli_runner=runner)

    @pytest.fixture
    def app(self, runner):
        return self._make_app(runner)

    async def _select(self, pilot, repo_path):
        await pilot.click(_group(pilot.app, repo_path).query_one(".title"))
        await pilot.pause()

    def _trash(self, pilot, name):
        return pilot.app.query_one(f"#sess-{name}", SessionRow).query_one(".trash")

    @pytest.mark.asyncio
    async def test_trash_icons_follow_selection(self, app):
        async with app.run_test(size=(80, 60)) as pilot:
            assert not self._trash(pilot, "fox").display
            await self._select(pilot, "/fake/alpha")
            assert self._trash(pilot, "fox").display
            assert self._trash(pilot, "bear").display
            assert not self._trash(pilot, "hawk").display

            await pilot.press("escape")
            await pilot.pause()
            assert not self._trash(pilot, "fox").display
            assert not self._trash(pilot, "bear").display

    @pytest.mark.asyncio
    async def test_clean_worktree_removes_immediately(self, app, runner, monkeypatch):
        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", lambda path: 0)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            assert runner.calls == [["remove", "bear", "-y"]]
            assert not pilot.app.query_one("#sess-bear", SessionRow).remove_pending
            assert _group(pilot.app, "/fake/alpha").selected

    @pytest.mark.asyncio
    async def test_main_session_skips_the_check(self, app, runner, monkeypatch):
        def boom(path):
            raise AssertionError("main sessions should not be checked")

        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", boom)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            await pilot.click(self._trash(pilot, "fox"))
            await pilot.pause()
            assert runner.calls == [["remove", "fox", "-y"]]

    @pytest.mark.asyncio
    async def test_dirty_worktree_asks_first(self, app, runner, monkeypatch):
        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", lambda path: 3)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            row = pilot.app.query_one("#sess-bear", SessionRow)
            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            assert row.remove_pending
            assert "3 uncommitted changes" in str(row.query_one(".confirm-text", Static).content)
            assert runner.calls == []

            await pilot.click(row.query_one(".confirm-no"))
            await pilot.pause()
            assert not row.remove_pending
            assert runner.calls == []

            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            await pilot.click(row.query_one(".confirm-yes"))
            await pilot.pause()
            assert runner.calls == [["remove", "bear", "-y"]]

    @pytest.mark.asyncio
    async def test_unknown_status_asks(self, app, runner, monkeypatch):
        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", lambda path: None)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            row = pilot.app.query_one("#sess-bear", SessionRow)
            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            assert row.remove_pending
            assert "Could not check" in str(row.query_one(".confirm-text", Static).content)
            assert runner.calls == []

    @pytest.mark.asyncio
    async def test_failed_remove_shows_error(self, monkeypatch):
        runner = _Runner(returncode=1, output="Removing...\nError: nope\n")
        app = self._make_app(runner)
        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", lambda path: 0)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            row = pilot.app.query_one("#sess-bear", SessionRow)
            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            assert len(runner.calls) == 1
            assert row.remove_pending
            assert "Error: nope" in str(row.query_one(".confirm-text", Static).content)

    @pytest.mark.asyncio
    async def test_pending_confirmation_keeps_selection_alive(self, app, monkeypatch):
        monkeypatch.setattr(snapshot_module, "count_uncommitted_changes", lambda path: 1)
        monkeypatch.setattr(sidebar_app_module, "SELECTION_INACTIVITY_TIMEOUT", 0.5)
        async with app.run_test(size=(80, 60)) as pilot:
            await self._select(pilot, "/fake/alpha")
            row = pilot.app.query_one("#sess-bear", SessionRow)
            await pilot.click(self._trash(pilot, "bear"))
            await pilot.pause()
            assert row.remove_pending

            await pilot.pause(1.2)
            assert _group(pilot.app, "/fake/alpha").selected
            assert row.remove_pending

            await pilot.click(row.query_one(".confirm-no"))
            await pilot.pause(1.2)
            assert not _group(pilot.app, "/fake/alpha").selected
            assert not self._trash(pilot, "bear").display
