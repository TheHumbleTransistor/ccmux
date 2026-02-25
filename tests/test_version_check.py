"""Tests for ccmux.version_check module."""

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


# --- get_state_version / set_state_version ---

def test_get_state_version_none(temp_state_dir):
    """No version stored returns None."""
    assert state.get_state_version() is None


def test_set_and_get_state_version(temp_state_dir):
    """Round-trip set then get."""
    state.set_state_version("1.2.3")
    assert state.get_state_version() == "1.2.3"


def test_set_state_version_overwrites(temp_state_dir):
    """set_state_version overwrites a previous version."""
    state.set_state_version("1.0.0")
    state.set_state_version("2.0.0")
    assert state.get_state_version() == "2.0.0"


def test_version_coexists_with_sessions(temp_state_dir):
    """Version field doesn't interfere with session data."""
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )
    state.set_state_version("1.0.0")

    assert state.get_state_version() == "1.0.0"
    sess = state.get_session("fox")
    assert sess is not None
    assert sess.repo_path == "/repo"


def test_version_survives_session_add_remove(temp_state_dir):
    """Adding and removing sessions doesn't lose the version stamp."""
    state.set_state_version("1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )
    state.remove_session("fox")
    assert state.get_state_version() == "1.0.0"


# --- check_version_mismatch ---

def test_exact_match_is_noop(temp_state_dir, monkeypatch):
    """When stored version matches __version__, nothing happens."""
    monkeypatch.setattr("ccmux.version_check.__version__", "1.0.0")
    state.set_state_version("1.0.0")

    from ccmux.version_check import check_version_mismatch

    # Should return without any side effects
    check_version_mismatch()
    assert state.get_state_version() == "1.0.0"


def test_no_stored_version_no_sessions_stamps(temp_state_dir, monkeypatch):
    """No stored version + no sessions → stamps version silently."""
    monkeypatch.setattr("ccmux.version_check.__version__", "1.0.0")

    from ccmux.version_check import check_version_mismatch

    check_version_mismatch()
    assert state.get_state_version() == "1.0.0"


def test_mismatch_no_active_tmux_stamps_silently(temp_state_dir, monkeypatch):
    """Version mismatch but no live tmux → stamps without prompting."""
    monkeypatch.setattr("ccmux.version_check.__version__", "2.0.0")
    state.set_state_version("1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )

    monkeypatch.setattr("ccmux.tmux_ops.tmux_session_exists", lambda name: False)

    from ccmux.version_check import check_version_mismatch

    check_version_mismatch()
    assert state.get_state_version() == "2.0.0"


def test_mismatch_active_tmux_user_confirms_kill(temp_state_dir, monkeypatch):
    """Version mismatch + active tmux + user confirms → kills sessions and stamps."""
    monkeypatch.setattr("ccmux.version_check.__version__", "2.0.0")
    state.set_state_version("1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )

    monkeypatch.setattr("ccmux.tmux_ops.tmux_session_exists", lambda name: True)

    kill_calls = []
    monkeypatch.setattr(
        "ccmux.tmux_ops.kill_all_ccmux_sessions",
        lambda *args: kill_calls.append(args),
    )

    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)

    from ccmux.version_check import check_version_mismatch

    check_version_mismatch()
    assert state.get_state_version() == "2.0.0"
    assert len(kill_calls) == 1


def test_mismatch_active_tmux_user_declines(temp_state_dir, monkeypatch):
    """Version mismatch + active tmux + user declines → stamps but doesn't kill."""
    monkeypatch.setattr("ccmux.version_check.__version__", "2.0.0")
    state.set_state_version("1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )

    monkeypatch.setattr("ccmux.tmux_ops.tmux_session_exists", lambda name: True)

    kill_calls = []
    monkeypatch.setattr(
        "ccmux.tmux_ops.kill_all_ccmux_sessions",
        lambda *args: kill_calls.append(args),
    )

    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: False)

    from ccmux.version_check import check_version_mismatch

    check_version_mismatch()
    assert state.get_state_version() == "2.0.0"
    assert len(kill_calls) == 0


def test_no_stored_version_with_sessions_and_active_tmux(temp_state_dir, monkeypatch):
    """No stored version + existing sessions + live tmux → prompts."""
    monkeypatch.setattr("ccmux.version_check.__version__", "1.0.0")
    state.add_session(
        session_name="fox",
        repo_path="/repo",
        session_path="/repo/.worktrees/fox",
    )

    monkeypatch.setattr("ccmux.tmux_ops.tmux_session_exists", lambda name: True)

    kill_calls = []
    monkeypatch.setattr(
        "ccmux.tmux_ops.kill_all_ccmux_sessions",
        lambda *args: kill_calls.append(args),
    )

    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)

    from ccmux.version_check import check_version_mismatch

    check_version_mismatch()
    assert state.get_state_version() == "1.0.0"
    assert len(kill_calls) == 1
