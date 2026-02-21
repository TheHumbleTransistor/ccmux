"""Tests for ccmux.state module."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ccmux import state
from ccmux.state import store as state_store


@pytest.fixture
def temp_state_dir(monkeypatch):
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        monkeypatch.setattr(state_store, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state_store, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


def test_load_raw_empty(temp_state_dir):
    """Test loading state when no state file exists."""
    result = state_store._load_raw()
    assert result == {
        "sessions": {},
        "default_session": "default"
    }


def test_save_and_load_raw(temp_state_dir):
    """Test saving and loading raw state."""
    test_state = {
        "sessions": {
            "test-session": {
                "tmux_session_id": "$0",
                "instances": {}
            }
        },
        "default_session": "default"
    }

    state_store._save_raw(test_state)
    loaded = state_store._load_raw()

    assert loaded == test_state


def test_add_instance(temp_state_dir):
    """Test adding an instance to state."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    loaded = state_store._load_raw()
    assert "test-session" in loaded["sessions"]
    assert "feature-x" in loaded["sessions"]["test-session"]["instances"]

    wt = loaded["sessions"]["test-session"]["instances"]["feature-x"]
    assert wt["repo_path"] == "/repo"
    assert wt["instance_path"] == "/repo/.worktrees/feature-x"
    assert wt["tmux_window_id"] == "@1"
    assert loaded["sessions"]["test-session"]["tmux_session_id"] == "$0"


def test_remove_instance(temp_state_dir):
    """Test removing an instance from state."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    state.remove_instance("test-session", "feature-x")

    loaded = state_store._load_raw()
    assert "test-session" not in loaded["sessions"]


def test_remove_instance_keeps_session_with_other_instances(temp_state_dir):
    """Test that removing an instance keeps the session if other instances exist."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )
    state.add_instance(
        session_name="test-session",
        instance_name="feature-y",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-y"
    )

    state.remove_instance("test-session", "feature-x")

    loaded = state_store._load_raw()
    assert "test-session" in loaded["sessions"]
    assert "feature-x" not in loaded["sessions"]["test-session"]["instances"]
    assert "feature-y" in loaded["sessions"]["test-session"]["instances"]


def test_update_tmux_ids(temp_state_dir):
    """Test updating tmux IDs for an instance."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    state.update_tmux_ids(
        session_name="test-session",
        instance_name="feature-x",
        tmux_session_id="$1",
        tmux_window_id="@2"
    )

    loaded = state_store._load_raw()
    assert loaded["sessions"]["test-session"]["tmux_session_id"] == "$1"
    assert loaded["sessions"]["test-session"]["instances"]["feature-x"]["tmux_window_id"] == "@2"


def test_get_session(temp_state_dir):
    """Test getting a session from state."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    session = state.get_session("test-session")
    assert session is not None
    assert "feature-x" in session.instances
    assert session.instances["feature-x"].repo_path == "/repo"

    assert state.get_session("non-existent") is None


def test_get_instance(temp_state_dir):
    """Test getting a specific instance from state."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    inst = state.get_instance("test-session", "feature-x")
    assert inst is not None
    assert inst.repo_path == "/repo"

    assert state.get_instance("test-session", "non-existent") is None
    assert state.get_instance("non-existent", "feature-x") is None


def test_find_instance_by_tmux_ids(temp_state_dir):
    """Test finding an instance by tmux IDs."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    result = state.find_instance_by_tmux_ids("$0", "@1")
    assert result is not None
    session_name, instance_name, instance = result
    assert session_name == "test-session"
    assert instance_name == "feature-x"
    assert instance.repo_path == "/repo"

    assert state.find_instance_by_tmux_ids("$999", "@999") is None


def test_get_all_instances(temp_state_dir):
    """Test getting all instances."""
    state.add_instance(
        session_name="session-1",
        instance_name="feature-x",
        repo_path="/repo1",
        instance_path="/repo1/.worktrees/feature-x",
        tmux_window_id="@1"
    )
    state.add_instance(
        session_name="session-2",
        instance_name="feature-y",
        repo_path="/repo2",
        instance_path="/repo2/.worktrees/feature-y",
        tmux_window_id="@2"
    )

    all_insts = state.get_all_instances()
    assert len(all_insts) == 2
    assert any(inst.name == "feature-x" and inst.session == "session-1" for inst in all_insts)
    assert any(inst.name == "feature-y" and inst.session == "session-2" for inst in all_insts)

    session1_insts = state.get_all_instances("session-1")
    assert len(session1_insts) == 1
    assert session1_insts[0].name == "feature-x"
    assert session1_insts[0].session == "session-1"


def test_get_all_sessions(temp_state_dir):
    """Test getting all sessions."""
    state.add_instance(
        session_name="session-1",
        instance_name="feature-x",
        repo_path="/repo1",
        instance_path="/repo1/.worktrees/feature-x",
    )
    state.add_instance(
        session_name="session-2",
        instance_name="feature-y",
        repo_path="/repo2",
        instance_path="/repo2/.worktrees/feature-y",
    )

    sessions = state.get_all_sessions()
    assert len(sessions) == 2
    names = {s.name for s in sessions}
    assert names == {"session-1", "session-2"}

    for sess in sessions:
        assert len(sess.instances) == 1


def test_update_instance(temp_state_dir):
    """Test updating instance fields."""
    state.add_instance(
        session_name="test-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
    )

    assert state.update_instance("test-session", "feature-x", instance_path="/new/path")

    inst = state.get_instance("test-session", "feature-x")
    assert inst.instance_path == "/new/path"

    assert not state.update_instance("test-session", "nonexistent", instance_path="/x")
    assert not state.update_instance("nonexistent", "feature-x", instance_path="/x")


def test_rename_session(temp_state_dir):
    """Test renaming a session."""
    state.add_instance(
        session_name="old-session",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1",
    )

    assert state.rename_session("old-session", "new-session")

    loaded = state_store._load_raw()
    assert "old-session" not in loaded["sessions"]
    assert "new-session" in loaded["sessions"]
    assert "feature-x" in loaded["sessions"]["new-session"]["instances"]


def test_rename_session_updates_default(temp_state_dir):
    """Test renaming a session updates default_session if it matched."""
    state.add_instance(
        session_name="default",
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
    )
    s = state_store._load_raw()
    s["default_session"] = "default"
    state_store._save_raw(s)

    assert state.rename_session("default", "my-project")

    loaded = state_store._load_raw()
    assert loaded["default_session"] == "my-project"


def test_rename_session_conflict(temp_state_dir):
    """Test renaming a session to a name that already exists fails."""
    state.add_instance(
        session_name="session-a",
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )
    state.add_instance(
        session_name="session-b",
        instance_name="inst-b",
        repo_path="/repo",
        instance_path="/repo/.worktrees/b",
    )

    assert not state.rename_session("session-a", "session-b")
    loaded = state_store._load_raw()
    assert "session-a" in loaded["sessions"]
    assert "session-b" in loaded["sessions"]


def test_rename_session_not_found(temp_state_dir):
    """Test renaming a non-existent session returns False."""
    assert not state.rename_session("non-existent", "new-name")


def test_rename_instance(temp_state_dir):
    """Test renaming an instance within a session."""
    state.add_instance(
        session_name="test-session",
        instance_name="old-name",
        repo_path="/repo",
        instance_path="/repo/.worktrees/old-name",
        tmux_window_id="@1",
    )

    assert state.rename_instance("test-session", "old-name", "new-name")

    loaded = state_store._load_raw()
    instances = loaded["sessions"]["test-session"]["instances"]
    assert "old-name" not in instances
    assert "new-name" in instances
    assert instances["new-name"]["repo_path"] == "/repo"
    assert instances["new-name"]["tmux_window_id"] == "@1"


def test_rename_instance_conflict(temp_state_dir):
    """Test renaming an instance to a name that already exists fails."""
    state.add_instance(
        session_name="test-session",
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )
    state.add_instance(
        session_name="test-session",
        instance_name="inst-b",
        repo_path="/repo",
        instance_path="/repo/.worktrees/b",
    )

    assert not state.rename_instance("test-session", "inst-a", "inst-b")


def test_rename_instance_not_found(temp_state_dir):
    """Test renaming a non-existent instance returns False."""
    state.add_instance(
        session_name="test-session",
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )

    assert not state.rename_instance("test-session", "non-existent", "new-name")
    assert not state.rename_instance("non-existent-session", "inst-a", "new-name")


def test_remove_session(temp_state_dir):
    """Test removing an entire session."""
    state.add_instance(
        session_name="doomed-session",
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )
    state.add_instance(
        session_name="doomed-session",
        instance_name="inst-b",
        repo_path="/repo",
        instance_path="/repo/.worktrees/b",
    )

    assert state.remove_session("doomed-session")

    loaded = state_store._load_raw()
    assert "doomed-session" not in loaded["sessions"]


def test_remove_session_resets_default(temp_state_dir):
    """Test removing the default session resets default_session."""
    state.add_instance(
        session_name="my-default",
        instance_name="inst",
        repo_path="/repo",
        instance_path="/repo/.worktrees/inst",
    )
    s = state_store._load_raw()
    s["default_session"] = "my-default"
    state_store._save_raw(s)

    assert state.remove_session("my-default")

    loaded = state_store._load_raw()
    assert loaded["default_session"] == "default"


def test_remove_session_not_found(temp_state_dir):
    """Test removing a non-existent session returns False."""
    assert not state.remove_session("non-existent")


def test_corrupted_state_file(temp_state_dir):
    """Test loading a corrupted state file."""
    state_file = temp_state_dir / "state.json"
    state_file.write_text("invalid json {")

    result = state_store._load_raw()
    assert result == {
        "sessions": {},
        "default_session": "default"
    }


def test_instance_from_dict_worktree(temp_state_dir):
    """Test Instance.from_dict creates WorktreeInstance."""
    inst = state.Instance.from_dict("test", {
        "repo_path": "/repo",
        "instance_path": "/repo/.worktrees/test",
        "is_worktree": True,
    })
    assert inst.instance_path == "/repo/.worktrees/test"
    assert inst.is_worktree is True
    assert isinstance(inst, state.WorktreeInstance)


def test_instance_from_dict_main_repo(temp_state_dir):
    """Test Instance.from_dict creates MainRepoInstance when is_worktree=False."""
    inst = state.Instance.from_dict("main", {
        "repo_path": "/repo",
        "instance_path": "/repo",
        "is_worktree": False,
    })
    assert inst.is_worktree is False
    assert inst.instance_type == "main"
    assert isinstance(inst, state.MainRepoInstance)


def test_session_from_dict(temp_state_dir):
    """Test Session.from_dict constructs correctly."""
    session = state.Session.from_dict("test", {
        "tmux_session_id": "$0",
        "instances": {
            "fox": {
                "repo_path": "/repo",
                "instance_path": "/repo/.worktrees/fox",
                "is_worktree": True,
            }
        }
    })
    assert "fox" in session.instances
    assert session.instances["fox"].instance_path == "/repo/.worktrees/fox"


def test_find_main_repo_instance(temp_state_dir):
    """Test finding a main repo instance."""
    state.add_instance(
        session_name="test",
        instance_name="main-inst",
        repo_path="/repo",
        instance_path="/repo",
        is_worktree=False,
    )
    state.add_instance(
        session_name="test",
        instance_name="wt-inst",
        repo_path="/repo",
        instance_path="/repo/.worktrees/wt-inst",
        is_worktree=True,
    )

    result = state.find_main_repo_instance("/repo", "test")
    assert result is not None
    assert result.name == "main-inst"
    assert result.is_worktree is False

    assert state.find_main_repo_instance("/other-repo", "test") is None
