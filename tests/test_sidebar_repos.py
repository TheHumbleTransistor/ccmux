"""Tests for sidebar repo discovery (ccmux.ui.sidebar.repos)."""

import tempfile
from pathlib import Path

import pytest

from ccmux import config as config_module
from ccmux import state
from ccmux.state import store as state_store
from ccmux.ui.sidebar.repos import (
    RepoCandidate,
    discover_repos,
    filter_repos,
    looks_like_repo,
    resolve_typed_path,
    resolve_workspace_dirs,
)


@pytest.fixture
def temp_state_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        monkeypatch.setattr(state_store, "STATE_DIR", tmpdir_path)
        monkeypatch.setattr(state_store, "STATE_FILE", tmpdir_path / "state.json")
        yield tmpdir_path


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / ".git").mkdir()
    return path


def _make_bare(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n")
    (path / "objects").mkdir()
    (path / "refs").mkdir()
    return path


class TestLooksLikeRepo:
    def test_git_dir(self, tmp_path):
        assert looks_like_repo(_make_repo(tmp_path / "a"))

    def test_git_file(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../repo/.git/worktrees/wt\n")
        assert looks_like_repo(worktree)

    def test_bare_layout(self, tmp_path):
        assert looks_like_repo(_make_bare(tmp_path / "bare.git"))

    def test_plain_dir(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert not looks_like_repo(plain)


class TestDiscoverRepos:
    def test_finds_repos_one_level_down_sorted(self, tmp_path):
        ws = tmp_path / "ws"
        _make_repo(ws / "beta")
        _make_repo(ws / "alpha")
        _make_bare(ws / "bare.git")
        (ws / "plain").mkdir()
        _make_repo(ws / ".hidden")
        _make_repo(ws / "deep" / "nested")

        names = [c.name for c in discover_repos([ws], [])]
        assert names == ["alpha", "bare.git", "beta"]

    def test_known_repos_included_and_marked(self, tmp_path):
        ws = tmp_path / "ws"
        _make_repo(ws / "alpha")
        _make_repo(ws / "beta")
        elsewhere = _make_repo(tmp_path / "elsewhere" / "gamma")

        by_name = {c.name: c for c in discover_repos([ws], [str(ws / "alpha"), str(elsewhere)])}
        assert by_name["alpha"].has_session
        assert not by_name["beta"].has_session
        assert by_name["gamma"].has_session and by_name["gamma"].path == str(elsewhere)

    def test_duplicate_names_show_parent(self, tmp_path):
        first = _make_repo(tmp_path / "one" / "proj")
        second = _make_repo(tmp_path / "two" / "proj")
        displays = sorted(c.display for c in discover_repos([first.parent, second.parent], []))
        assert displays == [f"proj  ({first.parent})", f"proj  ({second.parent})"]

    def test_missing_workspace_dir_ignored(self, tmp_path):
        assert discover_repos([tmp_path / "nope"], []) == []


class TestFilterAndTypedPath:
    def test_filter_is_case_insensitive_substring(self):
        cands = [
            RepoCandidate("/a/Alpha", "Alpha", "Alpha", False),
            RepoCandidate("/a/beta", "beta", "beta", False),
        ]
        assert [c.name for c in filter_repos(cands, "LPH")] == ["Alpha"]
        assert len(filter_repos(cands, "  ")) == 2

    def test_typed_path_resolution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "proj").mkdir()
        assert resolve_typed_path("~/proj") == str(tmp_path / "proj")
        assert resolve_typed_path(str(tmp_path / "proj")) == str(tmp_path / "proj")
        assert resolve_typed_path("proj") is None
        assert resolve_typed_path(str(tmp_path / "missing")) is None
        assert resolve_typed_path("") is None


class TestResolveWorkspaceDirs:
    def test_configured_dirs_win(self, tmp_path, monkeypatch, temp_state_dir):
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = tmp_path / "config.toml"
        cfg.write_text(f'[sidebar]\nworkspace_dirs = ["{ws}"]\n')
        monkeypatch.setattr(config_module, "USER_CONFIG_FILE", cfg)
        repo = _make_repo(tmp_path / "code" / "proj")
        state.add_session("fox", str(repo), str(repo))

        assert resolve_workspace_dirs() == [ws]

    def test_falls_back_to_session_parents(self, tmp_path, monkeypatch, temp_state_dir):
        monkeypatch.setattr(config_module, "USER_CONFIG_FILE", tmp_path / "missing.toml")
        repo = _make_repo(tmp_path / "code" / "proj")
        repo2 = _make_repo(tmp_path / "code" / "proj2")
        state.add_session("fox", str(repo), str(repo))
        state.add_session("owl", str(repo2), str(repo2))

        assert resolve_workspace_dirs() == [tmp_path / "code"]
