"""Tests for ccmux.config — get_configured_backend()."""

from pathlib import Path

import pytest

from ccmux.backend import ClaudeCodeBackend, OpenCodeBackend
from ccmux.config import get_configured_backend


class TestGetConfiguredBackend:
    """Tests for get_configured_backend()."""

    def test_returns_default_when_repo_root_is_none(self):
        backend = get_configured_backend(repo_root=None)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_returns_default_when_no_config_file(self, tmp_path):
        # tmp_path has no ccmux.toml
        backend = get_configured_backend(repo_root=tmp_path)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_returns_default_when_config_has_no_backend_section(self, tmp_path):
        (tmp_path / "ccmux.toml").write_text('[worktree]\npost_create = ["echo hi"]\n')
        backend = get_configured_backend(repo_root=tmp_path)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_returns_configured_opencode_backend(self, tmp_path):
        (tmp_path / "ccmux.toml").write_text('[backend]\nname = "opencode"\n')
        backend = get_configured_backend(repo_root=tmp_path)
        assert isinstance(backend, OpenCodeBackend)

    def test_returns_configured_claude_backend(self, tmp_path):
        (tmp_path / "ccmux.toml").write_text('[backend]\nname = "claude"\n')
        backend = get_configured_backend(repo_root=tmp_path)
        assert isinstance(backend, ClaudeCodeBackend)

    def test_raises_for_unknown_backend(self, tmp_path):
        (tmp_path / "ccmux.toml").write_text('[backend]\nname = "unknown_tool"\n')
        with pytest.raises(ValueError, match="Unknown backend"):
            get_configured_backend(repo_root=tmp_path)

    def test_returns_default_when_config_is_malformed(self, tmp_path):
        (tmp_path / "ccmux.toml").write_text("this is not valid toml {{{{")
        backend = get_configured_backend(repo_root=tmp_path)
        assert isinstance(backend, ClaudeCodeBackend)
