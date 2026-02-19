"""Tests for ccmux.state module."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ccmux import state


@pytest.fixture
def temp_state_dir(monkeypatch):
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        monkeypatch.setattr(state, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


def test_load_state_empty(temp_state_dir):
    """Test loading state when no state file exists."""
    result = state.load_state()
    assert result == {
        "sessions": {},
        "default_session": "ccmux"
    }


def test_save_and_load_state(temp_state_dir):
    """Test saving and loading state."""
    test_state = {
        "sessions": {
            "test-session": {
                "tmux_session_id": "$0",
                "instances": {}
            }
        },
        "default_session": "ccmux"
    }

    state.save_state(test_state)
    loaded = state.load_state()

    assert loaded == test_state


def test_add_worktree(temp_state_dir):
    """Test adding a worktree to state."""
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    loaded = state.load_state()
    assert "test-session" in loaded["sessions"]
    assert "feature-x" in loaded["sessions"]["test-session"]["instances"]

    wt = loaded["sessions"]["test-session"]["instances"]["feature-x"]
    assert wt["repo_path"] == "/repo"
    assert wt["instance_path"] == "/repo/.worktrees/feature-x"
    assert wt["tmux_window_id"] == "@1"
    assert loaded["sessions"]["test-session"]["tmux_session_id"] == "$0"


def test_remove_worktree(temp_state_dir):
    """Test removing a worktree from state."""
    # Add a worktree first
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x"
    )

    # Remove it
    state.remove_worktree("test-session", "feature-x")

    loaded = state.load_state()
    # Session should be removed since it has no worktrees
    assert "test-session" not in loaded["sessions"]


def test_remove_worktree_keeps_session_with_other_worktrees(temp_state_dir):
    """Test that removing a worktree keeps the session if other worktrees exist."""
    # Add two worktrees
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x"
    )
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-y",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-y"
    )

    # Remove one
    state.remove_worktree("test-session", "feature-x")

    loaded = state.load_state()
    assert "test-session" in loaded["sessions"]
    assert "feature-x" not in loaded["sessions"]["test-session"]["instances"]
    assert "feature-y" in loaded["sessions"]["test-session"]["instances"]


def test_update_tmux_ids(temp_state_dir):
    """Test updating tmux IDs for a worktree."""
    # Add a worktree
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    # Update IDs
    state.update_tmux_ids(
        session_name="test-session",
        worktree_name="feature-x",
        tmux_session_id="$1",
        tmux_window_id="@2"
    )

    loaded = state.load_state()
    assert loaded["sessions"]["test-session"]["tmux_session_id"] == "$1"
    assert loaded["sessions"]["test-session"]["instances"]["feature-x"]["tmux_window_id"] == "@2"


def test_get_session(temp_state_dir):
    """Test getting a session from state."""
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x"
    )

    session = state.get_session("test-session")
    assert session is not None
    assert "instances" in session
    assert "feature-x" in session["instances"]

    # Non-existent session
    assert state.get_session("non-existent") is None


def test_get_worktree(temp_state_dir):
    """Test getting a specific worktree from state."""
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x"
    )

    wt = state.get_worktree("test-session", "feature-x")
    assert wt is not None
    assert wt["repo_path"] == "/repo"

    # Non-existent worktree
    assert state.get_worktree("test-session", "non-existent") is None
    assert state.get_worktree("non-existent", "feature-x") is None


def test_find_worktree_by_tmux_ids(temp_state_dir):
    """Test finding a worktree by tmux IDs."""
    state.add_worktree(
        session_name="test-session",
        worktree_name="feature-x",
        repo_path="/repo",
        worktree_path="/repo/.worktrees/feature-x",
        tmux_session_id="$0",
        tmux_window_id="@1"
    )

    result = state.find_worktree_by_tmux_ids("$0", "@1")
    assert result is not None
    session_name, worktree_name, worktree_data = result
    assert session_name == "test-session"
    assert worktree_name == "feature-x"
    assert worktree_data["repo_path"] == "/repo"

    # Non-existent IDs
    assert state.find_worktree_by_tmux_ids("$999", "@999") is None


def test_get_all_worktrees(temp_state_dir):
    """Test getting all worktrees."""
    state.add_worktree(
        session_name="session-1",
        worktree_name="feature-x",
        repo_path="/repo1",
        worktree_path="/repo1/.worktrees/feature-x",
        tmux_window_id="@1"
    )
    state.add_worktree(
        session_name="session-2",
        worktree_name="feature-y",
        repo_path="/repo2",
        worktree_path="/repo2/.worktrees/feature-y",
        tmux_window_id="@2"
    )

    # Get all worktrees
    all_wts = state.get_all_worktrees()
    assert len(all_wts) == 2
    assert any(wt["name"] == "feature-x" and wt["session"] == "session-1" for wt in all_wts)
    assert any(wt["name"] == "feature-y" and wt["session"] == "session-2" for wt in all_wts)

    # Get worktrees for specific session
    session1_wts = state.get_all_worktrees("session-1")
    assert len(session1_wts) == 1
    assert session1_wts[0]["name"] == "feature-x"
    assert session1_wts[0]["session"] == "session-1"


def test_corrupted_state_file(temp_state_dir):
    """Test loading a corrupted state file."""
    # Write invalid JSON
    state_file = temp_state_dir / "state.json"
    state_file.write_text("invalid json {")

    # Should return empty state instead of crashing
    result = state.load_state()
    assert result == {
        "sessions": {},
        "default_session": "ccmux"
    }
