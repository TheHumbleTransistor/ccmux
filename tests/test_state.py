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
    }


def test_save_and_load_raw(temp_state_dir):
    """Test saving and loading raw state."""
    test_state = {
        "sessions": {
            "default": {
                "tmux_session_id": "$0",
                "instances": {}
            }
        },
    }

    state_store._save_raw(test_state)
    loaded = state_store._load_raw()

    assert loaded == test_state


def test_add_instance(temp_state_dir):
    """Test adding an instance to state."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    loaded = state_store._load_raw()
    assert "default" in loaded["sessions"]
    assert "feature-x" in loaded["sessions"]["default"]["instances"]

    wt = loaded["sessions"]["default"]["instances"]["feature-x"]
    assert wt["repo_path"] == "/repo"
    assert wt["instance_path"] == "/repo/.worktrees/feature-x"
    assert wt["tmux_window_id"] == "@1"
    assert loaded["sessions"]["default"]["tmux_session_id"] == "$0"


def test_remove_instance(temp_state_dir):
    """Test removing an instance from state."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    state.remove_instance("feature-x")

    loaded = state_store._load_raw()
    assert "default" not in loaded["sessions"]


def test_remove_instance_keeps_session_with_other_instances(temp_state_dir):
    """Test that removing an instance keeps the session if other instances exist."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )
    state.add_instance(
        instance_name="feature-y",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-y"
    )

    state.remove_instance("feature-x")

    loaded = state_store._load_raw()
    assert "default" in loaded["sessions"]
    assert "feature-x" not in loaded["sessions"]["default"]["instances"]
    assert "feature-y" in loaded["sessions"]["default"]["instances"]


def test_update_tmux_ids(temp_state_dir):
    """Test updating tmux IDs for an instance."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    state.update_tmux_ids(
        instance_name="feature-x",
        tmux_session_id="$1",
        tmux_window_id="@2"
    )

    loaded = state_store._load_raw()
    assert loaded["sessions"]["default"]["tmux_session_id"] == "$1"
    assert loaded["sessions"]["default"]["instances"]["feature-x"]["tmux_window_id"] == "@2"


def test_get_session(temp_state_dir):
    """Test getting a session from state."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    session = state.get_session()
    assert session is not None
    assert "feature-x" in session.instances
    assert session.instances["feature-x"].repo_path == "/repo"

    assert state.get_session("non-existent") is None


def test_get_instance(temp_state_dir):
    """Test getting a specific instance from state."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x"
    )

    inst = state.get_instance("feature-x")
    assert inst is not None
    assert inst.repo_path == "/repo"

    assert state.get_instance("non-existent") is None


def test_find_instance_by_tmux_ids(temp_state_dir):
    """Test finding an instance by tmux IDs."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    result = state.find_instance_by_tmux_ids("$0", "@1")
    assert result is not None
    session_name, instance_name, instance = result
    assert session_name == "default"
    assert instance_name == "feature-x"
    assert instance.repo_path == "/repo"

    assert state.find_instance_by_tmux_ids("$999", "@999") is None


def test_get_all_instances(temp_state_dir):
    """Test getting all instances from the default session."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo1",
        instance_path="/repo1/.worktrees/feature-x",
        tmux_window_id="@1"
    )
    state.add_instance(
        instance_name="feature-y",
        repo_path="/repo2",
        instance_path="/repo2/.worktrees/feature-y",
        tmux_window_id="@2"
    )

    all_insts = state.get_all_instances()
    assert len(all_insts) == 2
    assert any(inst.name == "feature-x" for inst in all_insts)
    assert any(inst.name == "feature-y" for inst in all_insts)


def test_update_instance(temp_state_dir):
    """Test updating instance fields."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
    )

    assert state.update_instance("feature-x", instance_path="/new/path")

    inst = state.get_instance("feature-x")
    assert inst.instance_path == "/new/path"

    assert not state.update_instance("nonexistent", instance_path="/x")


def test_rename_instance(temp_state_dir):
    """Test renaming an instance within a session."""
    state.add_instance(
        instance_name="old-name",
        repo_path="/repo",
        instance_path="/repo/.worktrees/old-name",
        tmux_window_id="@1",
    )

    assert state.rename_instance("old-name", "new-name")

    loaded = state_store._load_raw()
    instances = loaded["sessions"]["default"]["instances"]
    assert "old-name" not in instances
    assert "new-name" in instances
    assert instances["new-name"]["repo_path"] == "/repo"
    assert instances["new-name"]["tmux_window_id"] == "@1"


def test_rename_instance_conflict(temp_state_dir):
    """Test renaming an instance to a name that already exists fails."""
    state.add_instance(
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )
    state.add_instance(
        instance_name="inst-b",
        repo_path="/repo",
        instance_path="/repo/.worktrees/b",
    )

    assert not state.rename_instance("inst-a", "inst-b")


def test_rename_instance_not_found(temp_state_dir):
    """Test renaming a non-existent instance returns False."""
    state.add_instance(
        instance_name="inst-a",
        repo_path="/repo",
        instance_path="/repo/.worktrees/a",
    )

    assert not state.rename_instance("non-existent", "new-name")
    assert not state.rename_instance("inst-a", "new-name", session_name="non-existent-session")


def test_corrupted_state_file(temp_state_dir):
    """Test loading a corrupted state file."""
    state_file = temp_state_dir / "state.json"
    state_file.write_text("invalid json {")

    result = state_store._load_raw()
    assert result == {
        "sessions": {},
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
        instance_name="main-inst",
        repo_path="/repo",
        instance_path="/repo",
        is_worktree=False,
    )
    state.add_instance(
        instance_name="wt-inst",
        repo_path="/repo",
        instance_path="/repo/.worktrees/wt-inst",
        is_worktree=True,
    )

    result = state.find_main_repo_instance("/repo")
    assert result is not None
    assert result.name == "main-inst"
    assert result.is_worktree is False

    assert state.find_main_repo_instance("/other-repo") is None


# --- find_instance_by_path tests ---

def test_find_instance_by_path_exact(temp_state_dir):
    """Test exact path match returns the instance."""
    state.add_instance(
        instance_name="fox",
        repo_path="/repo",
        instance_path="/repo/.worktrees/fox",
        is_worktree=True,
    )
    result = state.find_instance_by_path("/repo/.worktrees/fox")
    assert result is not None
    assert result[0] == "fox"


def test_find_instance_by_path_subdirectory(temp_state_dir):
    """Test subdirectory of instance_path matches."""
    state.add_instance(
        instance_name="fox",
        repo_path="/repo",
        instance_path="/repo/.worktrees/fox",
        is_worktree=True,
    )
    result = state.find_instance_by_path("/repo/.worktrees/fox/src/main.py")
    assert result is not None
    assert result[0] == "fox"


def test_find_instance_by_path_longest_prefix(temp_state_dir):
    """Test longest-prefix disambiguation: worktree wins over main repo."""
    state.add_instance(
        instance_name="main-inst",
        repo_path="/repo",
        instance_path="/repo",
        is_worktree=False,
    )
    state.add_instance(
        instance_name="fox",
        repo_path="/repo",
        instance_path="/repo/.worktrees/fox",
        is_worktree=True,
    )
    result = state.find_instance_by_path("/repo/.worktrees/fox/src")
    assert result is not None
    assert result[0] == "fox"


def test_find_instance_by_path_no_match(temp_state_dir):
    """Test no match returns None."""
    state.add_instance(
        instance_name="fox",
        repo_path="/repo",
        instance_path="/repo/.worktrees/fox",
        is_worktree=True,
    )
    result = state.find_instance_by_path("/other/path")
    assert result is None


def test_find_instance_by_path_no_false_prefix(temp_state_dir):
    """Test /repo doesn't false-match /repo2."""
    state.add_instance(
        instance_name="main-inst",
        repo_path="/repo",
        instance_path="/repo",
        is_worktree=False,
    )
    result = state.find_instance_by_path("/repo2/somefile")
    assert result is None


# --- claude_session_id tests ---

def test_add_instance_with_claude_session_id(temp_state_dir):
    """Test adding an instance with claude_session_id."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
        claude_session_id="abc-123",
    )

    loaded = state_store._load_raw()
    inst = loaded["sessions"]["default"]["instances"]["feature-x"]
    assert inst["claude_session_id"] == "abc-123"


def test_add_instance_without_claude_session_id(temp_state_dir):
    """Test adding an instance without claude_session_id omits the field."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
    )

    loaded = state_store._load_raw()
    inst = loaded["sessions"]["default"]["instances"]["feature-x"]
    assert "claude_session_id" not in inst


def test_claude_session_id_from_dict_present(temp_state_dir):
    """Test Instance.from_dict picks up claude_session_id when present."""
    inst = state.Instance.from_dict("test", {
        "repo_path": "/repo",
        "instance_path": "/repo/.worktrees/test",
        "is_worktree": True,
        "claude_session_id": "sess-456",
    })
    assert inst.claude_session_id == "sess-456"


def test_claude_session_id_from_dict_missing(temp_state_dir):
    """Test Instance.from_dict defaults claude_session_id to None for legacy data."""
    inst = state.Instance.from_dict("test", {
        "repo_path": "/repo",
        "instance_path": "/repo/.worktrees/test",
        "is_worktree": True,
    })
    assert inst.claude_session_id is None


def test_claude_session_id_to_dict(temp_state_dir):
    """Test Instance.to_dict includes claude_session_id when set."""
    inst = state.WorktreeInstance(
        name="test",
        repo_path="/repo",
        instance_path="/repo/.worktrees/test",
        claude_session_id="sess-789",
    )
    d = inst.to_dict()
    assert d["claude_session_id"] == "sess-789"


def test_claude_session_id_to_dict_none(temp_state_dir):
    """Test Instance.to_dict omits claude_session_id when None."""
    inst = state.WorktreeInstance(
        name="test",
        repo_path="/repo",
        instance_path="/repo/.worktrees/test",
    )
    d = inst.to_dict()
    assert "claude_session_id" not in d


def test_update_instance_claude_session_id(temp_state_dir):
    """Test updating claude_session_id via update_instance."""
    state.add_instance(
        instance_name="feature-x",
        repo_path="/repo",
        instance_path="/repo/.worktrees/feature-x",
    )

    state.update_instance("feature-x", claude_session_id="new-sess-id")

    loaded = state_store._load_raw()
    inst = loaded["sessions"]["default"]["instances"]["feature-x"]
    assert inst["claude_session_id"] == "new-sess-id"


def test_rename_preserves_claude_session_id(temp_state_dir):
    """Test that renaming an instance preserves claude_session_id."""
    state.add_instance(
        instance_name="old-name",
        repo_path="/repo",
        instance_path="/repo/.worktrees/old-name",
        claude_session_id="preserved-id",
    )

    assert state.rename_instance("old-name", "new-name")

    loaded = state_store._load_raw()
    instances = loaded["sessions"]["default"]["instances"]
    assert "old-name" not in instances
    assert "new-name" in instances
    assert instances["new-name"]["claude_session_id"] == "preserved-id"
