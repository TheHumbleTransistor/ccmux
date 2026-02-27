"""Tests for ccmux.session_ops module."""

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


# --- get_tmux_session_version / set_tmux_session_version ---

def test_get_tmux_session_version_none(temp_state_dir):
    """No version stored returns None."""
    assert state.get_tmux_session_version() is None


def test_set_and_get_tmux_session_version(temp_state_dir):
    """Round-trip set then get."""
    state.set_tmux_session_version("1.2.3")
    assert state.get_tmux_session_version() == "1.2.3"


def test_set_tmux_session_version_overwrites(temp_state_dir):
    """set_tmux_session_version overwrites a previous version."""
    state.set_tmux_session_version("1.0.0")
    state.set_tmux_session_version("2.0.0")
    assert state.get_tmux_session_version() == "2.0.0"


def test_version_coexists_with_sessions(temp_state_dir):
    """Version field doesn't interfere with session data."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
    )
    state.set_tmux_session_version("1.0.0")

    assert state.get_tmux_session_version() == "1.0.0"
    sess = state.get_session("fox")
    assert sess is not None
    assert sess.repo_path == "/repo"


def test_version_survives_session_add_remove(temp_state_dir):
    """Adding and removing sessions doesn't lose the version stamp."""
    state.set_tmux_session_version("1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.ccmux/worktrees/fox",
    )
    state.remove_session("fox")
    assert state.get_tmux_session_version() == "1.0.0"


# --- stale_sessions_running ---

def test_no_tmux_running_returns_false(temp_state_dir, monkeypatch):
    """No live tmux session → returns False regardless of version state."""
    monkeypatch.setattr("ccmux.session_ops.__version__", "2.0.0")
    state.set_tmux_session_version("1.0.0")

    monkeypatch.setattr("ccmux.session_ops.tmux_session_exists", lambda name: False)

    from ccmux.session_ops import stale_sessions_running

    assert stale_sessions_running() is False


def test_matching_version_returns_false(temp_state_dir, monkeypatch):
    """Live tmux + matching version → returns False."""
    monkeypatch.setattr("ccmux.session_ops.__version__", "1.0.0")
    state.set_tmux_session_version("1.0.0")

    monkeypatch.setattr("ccmux.session_ops.tmux_session_exists", lambda name: True)

    from ccmux.session_ops import stale_sessions_running

    assert stale_sessions_running() is False


def test_mismatched_version_returns_true(temp_state_dir, monkeypatch):
    """Live tmux + different version → returns True."""
    monkeypatch.setattr("ccmux.session_ops.__version__", "2.0.0")
    state.set_tmux_session_version("1.0.0")

    monkeypatch.setattr("ccmux.session_ops.tmux_session_exists", lambda name: True)

    from ccmux.session_ops import stale_sessions_running

    assert stale_sessions_running() is True


def test_no_stored_version_with_active_tmux_returns_true(temp_state_dir, monkeypatch):
    """No stored version + live tmux → returns True (pre-tracking upgrade)."""
    monkeypatch.setattr("ccmux.session_ops.__version__", "1.0.0")
    # No set_tmux_session_version call — stored is None

    monkeypatch.setattr("ccmux.session_ops.tmux_session_exists", lambda name: True)

    from ccmux.session_ops import stale_sessions_running

    assert stale_sessions_running() is True


def test_no_side_effects(temp_state_dir, monkeypatch):
    """stale_sessions_running() does not modify state."""
    monkeypatch.setattr("ccmux.session_ops.__version__", "2.0.0")
    state.set_tmux_session_version("1.0.0")

    monkeypatch.setattr("ccmux.session_ops.tmux_session_exists", lambda name: True)

    from ccmux.session_ops import stale_sessions_running

    stale_sessions_running()
    # Version should remain unchanged
    assert state.get_tmux_session_version() == "1.0.0"
