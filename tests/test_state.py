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
        "tmux_session_id": "$0",
        "sessions": {},
    }

    state_store._save_raw(test_state)
    loaded = state_store._load_raw()

    assert loaded == test_state


def test_add_session(temp_state_dir):
    """Test adding a session to state."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
        tmux_session_id="$0",
        tmux_cc_window_id="@1"
    )

    loaded = state_store._load_raw()
    assert "feature-x" in loaded["sessions"]

    sess = loaded["sessions"]["feature-x"]
    assert sess["repo_path"] == "/repo"
    assert sess["session_path"] == "/repo/.ccmux/worktrees/feature-x"
    assert sess["tmux_window_ids"]["claude_code"] == "@1"
    assert loaded["tmux_session_id"] == "$0"


def test_remove_session(temp_state_dir):
    """Test removing a session from state."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x"
    )

    state.remove_session("feature-x")

    loaded = state_store._load_raw()
    assert "feature-x" not in loaded["sessions"]


def test_remove_session_keeps_other_sessions(temp_state_dir):
    """Test that removing a session keeps other sessions."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x"
    )
    state.add_session(
        session_name="feature-y",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-y"
    )

    state.remove_session("feature-x")

    loaded = state_store._load_raw()
    assert "feature-x" not in loaded["sessions"]
    assert "feature-y" in loaded["sessions"]


def test_update_tmux_ids(temp_state_dir):
    """Test updating tmux IDs for a session."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
        tmux_session_id="$0",
        tmux_cc_window_id="@1"
    )

    state.update_tmux_ids(
        session_name="feature-x",
        tmux_session_id="$1",
        tmux_cc_window_id="@2"
    )

    loaded = state_store._load_raw()
    assert loaded["tmux_session_id"] == "$1"
    assert loaded["sessions"]["feature-x"]["tmux_window_ids"]["claude_code"] == "@2"


def test_get_session(temp_state_dir):
    """Test getting a session from state."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x"
    )

    session = state.get_session("feature-x")
    assert session is not None
    assert session.repo_path == "/repo"

    assert state.get_session("non-existent") is None


def test_get_all_sessions(temp_state_dir):
    """Test getting all sessions."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo1",
        session_path="/repo1/.ccmux/worktrees/feature-x",
        tmux_cc_window_id="@1"
    )
    state.add_session(
        session_name="feature-y",
        repo_path="/repo2",
        session_path="/repo2/.ccmux/worktrees/feature-y",
        tmux_cc_window_id="@2"
    )

    all_sessions = state.get_all_sessions()
    assert len(all_sessions) == 2
    assert any(sess.name == "feature-x" for sess in all_sessions)
    assert any(sess.name == "feature-y" for sess in all_sessions)


def test_update_session(temp_state_dir):
    """Test updating session fields."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
    )

    assert state.update_session("feature-x", session_path="/new/path")

    sess = state.get_session("feature-x")
    assert sess.session_path == "/new/path"

    assert not state.update_session("nonexistent", session_path="/x")


def test_rename_session(temp_state_dir):
    """Test renaming a session."""
    state.add_session(
        session_name="old-name",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/old-name",
        tmux_cc_window_id="@1",
    )

    assert state.rename_session("old-name", "new-name")

    loaded = state_store._load_raw()
    sessions = loaded["sessions"]
    assert "old-name" not in sessions
    assert "new-name" in sessions
    assert sessions["new-name"]["repo_path"] == "/repo"
    assert sessions["new-name"]["tmux_window_ids"]["claude_code"] == "@1"


def test_rename_session_conflict(temp_state_dir):
    """Test renaming a session to a name that already exists fails."""
    state.add_session(
        session_name="sess-a",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/a",
    )
    state.add_session(
        session_name="sess-b",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/b",
    )

    assert not state.rename_session("sess-a", "sess-b")


def test_rename_session_not_found(temp_state_dir):
    """Test renaming a non-existent session returns False."""
    state.add_session(
        session_name="sess-a",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/a",
    )

    assert not state.rename_session("non-existent", "new-name")


def test_corrupted_state_file(temp_state_dir):
    """Test loading a corrupted state file."""
    state_file = temp_state_dir / "state.json"
    state_file.write_text("invalid json {")

    result = state_store._load_raw()
    assert result == {
        "sessions": {},
    }


def test_session_from_dict_worktree(temp_state_dir):
    """Test Session.from_dict creates WorktreeSession."""
    sess = state.Session.from_dict("test", {
        "repo_path": "/repo",
        "session_path": "/repo/.ccmux/worktrees/test",
        "is_worktree": True,
    })
    assert sess.session_path == "/repo/.ccmux/worktrees/test"
    assert sess.is_worktree is True
    assert isinstance(sess, state.WorktreeSession)


def test_session_from_dict_main_repo(temp_state_dir):
    """Test Session.from_dict creates MainRepoSession when is_worktree=False."""
    sess = state.Session.from_dict("main", {
        "repo_path": "/repo",
        "session_path": "/repo",
        "is_worktree": False,
    })
    assert sess.is_worktree is False
    assert sess.session_type == "main"
    assert isinstance(sess, state.MainRepoSession)


def test_session_from_dict_compat_instance_path(temp_state_dir):
    """Test Session.from_dict reads legacy instance_path field."""
    sess = state.Session.from_dict("test", {
        "repo_path": "/repo",
        "instance_path": "/repo/.ccmux/worktrees/test",
        "is_worktree": True,
    })
    assert sess.session_path == "/repo/.ccmux/worktrees/test"


def test_find_main_repo_session(temp_state_dir):
    """Test finding a main repo session."""
    state.add_session(
        session_name="main-sess",
        repo_path="/repo",
        session_path="/repo",
        is_worktree=False,
    )
    state.add_session(
        session_name="wt-sess",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/wt-sess",
        is_worktree=True,
    )

    result = state.find_main_repo_session("/repo")
    assert result is not None
    assert result.name == "main-sess"
    assert result.is_worktree is False

    assert state.find_main_repo_session("/other-repo") is None


# --- find_session_by_path tests ---

def test_find_session_by_path_exact(temp_state_dir):
    """Test exact path match returns the session."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        is_worktree=True,
    )
    result = state.find_session_by_path("/repo/.ccmux/worktrees/fox")
    assert result is not None
    assert result[0] == "fox"


def test_find_session_by_path_subdirectory(temp_state_dir):
    """Test subdirectory of session_path matches."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        is_worktree=True,
    )
    result = state.find_session_by_path("/repo/.ccmux/worktrees/fox/src/main.py")
    assert result is not None
    assert result[0] == "fox"


def test_find_session_by_path_longest_prefix(temp_state_dir):
    """Test longest-prefix disambiguation: worktree wins over main repo."""
    state.add_session(
        session_name="main-sess",
        repo_path="/repo",
        session_path="/repo",
        is_worktree=False,
    )
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        is_worktree=True,
    )
    result = state.find_session_by_path("/repo/.ccmux/worktrees/fox/src")
    assert result is not None
    assert result[0] == "fox"


def test_find_session_by_path_no_match(temp_state_dir):
    """Test no match returns None."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        is_worktree=True,
    )
    result = state.find_session_by_path("/other/path")
    assert result is None


def test_find_session_by_path_no_false_prefix(temp_state_dir):
    """Test /repo doesn't false-match /repo2."""
    state.add_session(
        session_name="main-sess",
        repo_path="/repo",
        session_path="/repo",
        is_worktree=False,
    )
    result = state.find_session_by_path("/repo2/somefile")
    assert result is None


# --- claude_session_id tests ---

def test_add_session_with_claude_session_id(temp_state_dir):
    """Test adding a session with claude_session_id."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
        claude_session_id="abc-123",
    )

    loaded = state_store._load_raw()
    sess = loaded["sessions"]["feature-x"]
    assert sess["claude_session_id"] == "abc-123"


def test_add_session_without_claude_session_id(temp_state_dir):
    """Test adding a session without claude_session_id omits the field."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
    )

    loaded = state_store._load_raw()
    sess = loaded["sessions"]["feature-x"]
    assert "claude_session_id" not in sess


def test_claude_session_id_from_dict_present(temp_state_dir):
    """Test Session.from_dict picks up claude_session_id when present."""
    sess = state.Session.from_dict("test", {
        "repo_path": "/repo",
        "session_path": "/repo/.ccmux/worktrees/test",
        "is_worktree": True,
        "claude_session_id": "sess-456",
    })
    assert sess.claude_session_id == "sess-456"


def test_claude_session_id_from_dict_missing(temp_state_dir):
    """Test Session.from_dict defaults claude_session_id to None for legacy data."""
    sess = state.Session.from_dict("test", {
        "repo_path": "/repo",
        "session_path": "/repo/.ccmux/worktrees/test",
        "is_worktree": True,
    })
    assert sess.claude_session_id is None


def test_claude_session_id_to_dict(temp_state_dir):
    """Test Session.to_dict includes claude_session_id when set."""
    sess = state.WorktreeSession(
        name="test",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/test",
        claude_session_id="sess-789",
    )
    d = sess.to_dict()
    assert d["claude_session_id"] == "sess-789"


def test_claude_session_id_to_dict_none(temp_state_dir):
    """Test Session.to_dict omits claude_session_id when None."""
    sess = state.WorktreeSession(
        name="test",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/test",
    )
    d = sess.to_dict()
    assert "claude_session_id" not in d


def test_update_session_claude_session_id(temp_state_dir):
    """Test updating claude_session_id via update_session."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
    )

    state.update_session("feature-x", claude_session_id="new-sess-id")

    loaded = state_store._load_raw()
    sess = loaded["sessions"]["feature-x"]
    assert sess["claude_session_id"] == "new-sess-id"


def test_rename_preserves_claude_session_id(temp_state_dir):
    """Test that renaming a session preserves claude_session_id."""
    state.add_session(
        session_name="old-name",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/old-name",
        claude_session_id="preserved-id",
    )

    assert state.rename_session("old-name", "new-name")

    loaded = state_store._load_raw()
    sessions = loaded["sessions"]
    assert "old-name" not in sessions
    assert "new-name" in sessions
    assert sessions["new-name"]["claude_session_id"] == "preserved-id"


# --- Migration tests ---

def test_migrate_old_nested_format(temp_state_dir):
    """Test that old nested format (sessions.default.instances) is migrated on read."""
    old_state = {
        "sessions": {
            "default": {
                "tmux_session_id": "$0",
                "instances": {
                    "fox": {
                        "repo_path": "/repo",
                        "instance_path": "/repo/.ccmux/worktrees/fox",
                        "is_worktree": True,
                        "tmux_window_id": "@1",
                    }
                }
            }
        }
    }
    state_file = temp_state_dir / "state.json"
    with open(state_file, 'w') as f:
        json.dump(old_state, f)

    loaded = state_store._load_raw()
    # Should be flattened: fox at top-level sessions, no "default" key
    assert "default" not in loaded["sessions"]
    assert "fox" in loaded["sessions"]
    assert loaded["sessions"]["fox"]["session_path"] == "/repo/.ccmux/worktrees/fox"
    assert loaded["tmux_session_id"] == "$0"


def test_find_session_by_tmux_ids(temp_state_dir):
    """Test finding a session by tmux IDs."""
    state.add_session(
        session_name="feature-x",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/feature-x",
        tmux_session_id="$0",
        tmux_cc_window_id="@1"
    )

    result = state.find_session_by_tmux_ids("$0", "@1")
    assert result is not None
    session_name, session = result
    assert session_name == "feature-x"
    assert session.repo_path == "/repo"

    assert state.find_session_by_tmux_ids("$999", "@999") is None


# --- Session ID tests ---

def test_add_session_assigns_id(temp_state_dir):
    """Test that add_session auto-assigns incrementing IDs."""
    state.add_session(
        session_name="sess-a",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/a",
    )
    state.add_session(
        session_name="sess-b",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/b",
    )
    state.add_session(
        session_name="sess-c",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/c",
    )

    loaded = state_store._load_raw()
    assert loaded["sessions"]["sess-a"]["id"] == 1
    assert loaded["sessions"]["sess-b"]["id"] == 2
    assert loaded["sessions"]["sess-c"]["id"] == 3
    assert loaded["next_id"] == 4


def test_migration_backfills_id(temp_state_dir):
    """Test that legacy sessions without id get sequential IDs on load."""
    legacy_state = {
        "sessions": {
            "fox": {
                "repo_path": "/repo",
                "session_path": "/repo/.ccmux/worktrees/fox",
                "is_worktree": True,
                "tmux_window_id": "@1",
            },
            "bear": {
                "repo_path": "/repo",
                "session_path": "/repo",
                "is_worktree": False,
                "tmux_window_id": "@2",
            },
        }
    }
    state_file = temp_state_dir / "state.json"
    with open(state_file, 'w') as f:
        json.dump(legacy_state, f)

    loaded = state_store._load_raw()
    assert loaded["sessions"]["fox"]["id"] == 1
    assert loaded["sessions"]["bear"]["id"] == 2
    assert loaded["next_id"] == 3


def test_rename_preserves_id(temp_state_dir):
    """Test that renaming a session preserves its id."""
    state.add_session(
        session_name="old-name",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/old-name",
    )

    loaded = state_store._load_raw()
    original_id = loaded["sessions"]["old-name"]["id"]

    assert state.rename_session("old-name", "new-name")

    loaded = state_store._load_raw()
    assert loaded["sessions"]["new-name"]["id"] == original_id


# --- Window ID lifecycle tests ---

def test_clear_tmux_window_ids(temp_state_dir):
    """Test that clear_tmux_window_ids sets both IDs to None."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        tmux_cc_window_id="@9",
        tmux_bash_window_id="@10",
    )

    assert state.clear_tmux_window_ids("fox")

    sess = state.get_session("fox")
    assert sess.tmux_cc_window_id is None
    assert sess.tmux_bash_window_id is None


def test_clear_tmux_window_ids_not_found(temp_state_dir):
    """Test that clear_tmux_window_ids returns False for missing session."""
    assert not state.clear_tmux_window_ids("nonexistent")


def test_add_session_with_bash_window_id(temp_state_dir):
    """Test adding a session with both window IDs stores and retrieves correctly."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        tmux_cc_window_id="@5",
        tmux_bash_window_id="@6",
    )

    sess = state.get_session("fox")
    assert sess.tmux_cc_window_id == "@5"
    assert sess.tmux_bash_window_id == "@6"


def test_session_to_dict_nested_window_ids(temp_state_dir):
    """Test Session.to_dict uses nested dict format for window IDs."""
    sess = state.WorktreeSession(
        name="test",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/test",
        tmux_cc_window_id="@9",
        tmux_bash_window_id="@10",
    )
    d = sess.to_dict()
    assert d["tmux_window_ids"] == {
        "claude_code": "@9",
        "bash_terminal": "@10",
    }
    assert "tmux_window_id" not in d


def test_update_tmux_ids_with_bash(temp_state_dir):
    """Test updating both CC and bash window IDs."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
        tmux_cc_window_id="@1",
    )

    state.update_tmux_ids("fox", tmux_cc_window_id="@5", tmux_bash_window_id="@6")

    sess = state.get_session("fox")
    assert sess.tmux_cc_window_id == "@5"
    assert sess.tmux_bash_window_id == "@6"
