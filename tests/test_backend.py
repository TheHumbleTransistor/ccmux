"""Tests for the ccmux.backend module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ccmux.backend import (
    Backend,
    ClaudeCodeBackend,
    OpenCodeBackend,
    get_available_backends,
    get_backend,
    get_default_backend,
)


class TestClaudeCodeBackend:
    """Tests for ClaudeCodeBackend."""

    def setup_method(self):
        self.backend = ClaudeCodeBackend()

    def test_name(self):
        assert self.backend.name == "claude"

    def test_display_name(self):
        assert self.backend.display_name == "Claude Code"

    def test_binary_name(self):
        assert self.backend.binary_name == "claude"

    def test_env_vars_to_unset(self):
        assert "CLAUDECODE" in self.backend.env_vars_to_unset

    def test_install_instructions_not_empty(self):
        instructions = self.backend.install_instructions()
        assert len(instructions) > 0
        assert any("claude-code" in line for line in instructions)

    def test_build_launch_command_new_session(self):
        cmd = self.backend.build_launch_command("sess", "abc-123", resume=False)
        assert "--session-id abc-123" in cmd
        assert "--resume" not in cmd

    def test_build_launch_command_resume(self):
        cmd = self.backend.build_launch_command("sess", "abc-123", resume=True)
        assert "--resume abc-123" in cmd
        assert "--session-id" not in cmd

    def test_build_launch_command_resume_fallback(self):
        cmd = self.backend.build_launch_command("sess", "abc-123", resume=True)
        assert "claude --resume abc-123 || claude" in cmd

    def test_project_dir_not_none(self):
        result = self.backend.project_dir("/some/path")
        assert result is not None
        assert ".claude" in str(result)
        assert "projects" in str(result)

    def test_project_dir_encodes_slashes_as_dashes(self):
        result = self.backend.project_dir("/home/user/my-project")
        assert result.name == "-home-user-my-project"

    def test_project_dir_encodes_special_chars(self):
        result = self.backend.project_dir("/tmp/foo bar/baz.git")
        # spaces, dots, slashes all become dashes
        assert result.name == "-tmp-foo-bar-baz-git"

    def test_project_dir_preserves_alphanumeric(self):
        result = self.backend.project_dir("abc123")
        assert result.name == "abc123"

    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_check_installed_true(self, mock_which):
        assert self.backend.check_installed() is True

    @patch("shutil.which", return_value=None)
    def test_check_installed_false(self, mock_which):
        assert self.backend.check_installed() is False

    def test_is_backend_protocol(self):
        assert isinstance(self.backend, Backend)


class TestClaudeMigrateSessionData:
    """Tests for ClaudeCodeBackend.migrate_session_data()."""

    def setup_method(self):
        self.backend = ClaudeCodeBackend()

    def test_returns_false_when_old_dir_missing(self, tmp_path):
        """No migration if the old project dir doesn't exist."""
        result = self.backend.migrate_session_data(
            str(tmp_path / "nonexistent"), str(tmp_path / "new"), "sess-id"
        )
        assert result is False

    def test_copies_jsonl_file(self, tmp_path):
        """The .jsonl file is copied from old to new project dir."""
        session_id = "abc-123"
        old_dir = self.backend.project_dir(str(tmp_path / "old"))
        new_dir = self.backend.project_dir(str(tmp_path / "new"))
        old_dir.mkdir(parents=True)

        jsonl = old_dir / f"{session_id}.jsonl"
        jsonl.write_text('{"msg": "hello"}\n')

        result = self.backend.migrate_session_data(
            str(tmp_path / "old"), str(tmp_path / "new"), session_id
        )
        assert result is True
        assert (new_dir / f"{session_id}.jsonl").exists()
        assert (new_dir / f"{session_id}.jsonl").read_text() == '{"msg": "hello"}\n'

    def test_copies_session_subdir(self, tmp_path):
        """A session subdirectory is copied from old to new project dir."""
        session_id = "abc-123"
        old_dir = self.backend.project_dir(str(tmp_path / "old"))
        new_dir = self.backend.project_dir(str(tmp_path / "new"))
        old_dir.mkdir(parents=True)

        subdir = old_dir / session_id
        subdir.mkdir()
        (subdir / "data.json").write_text('{"key": "val"}')

        result = self.backend.migrate_session_data(
            str(tmp_path / "old"), str(tmp_path / "new"), session_id
        )
        assert result is True
        assert (new_dir / session_id / "data.json").exists()

    def test_copies_both_jsonl_and_subdir(self, tmp_path):
        """Both .jsonl and subdir are copied when both exist."""
        session_id = "abc-123"
        old_dir = self.backend.project_dir(str(tmp_path / "old"))
        new_dir = self.backend.project_dir(str(tmp_path / "new"))
        old_dir.mkdir(parents=True)

        (old_dir / f"{session_id}.jsonl").write_text("line\n")
        subdir = old_dir / session_id
        subdir.mkdir()
        (subdir / "f.txt").write_text("content")

        result = self.backend.migrate_session_data(
            str(tmp_path / "old"), str(tmp_path / "new"), session_id
        )
        assert result is True
        assert (new_dir / f"{session_id}.jsonl").exists()
        assert (new_dir / session_id / "f.txt").exists()

    def test_returns_false_when_no_matching_files(self, tmp_path):
        """Returns False when old dir exists but has no matching session files."""
        old_dir = self.backend.project_dir(str(tmp_path / "old"))
        old_dir.mkdir(parents=True)
        (old_dir / "unrelated.txt").write_text("nope")

        result = self.backend.migrate_session_data(
            str(tmp_path / "old"), str(tmp_path / "new"), "no-match"
        )
        assert result is False

    def test_replaces_existing_dest_subdir(self, tmp_path):
        """If the destination subdir already exists, it is replaced."""
        session_id = "abc-123"
        old_dir = self.backend.project_dir(str(tmp_path / "old"))
        new_dir = self.backend.project_dir(str(tmp_path / "new"))
        old_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)

        # Create old session subdir with new content
        old_sub = old_dir / session_id
        old_sub.mkdir()
        (old_sub / "new_file.txt").write_text("new")

        # Create existing dest subdir with stale content
        dest_sub = new_dir / session_id
        dest_sub.mkdir()
        (dest_sub / "stale.txt").write_text("stale")

        result = self.backend.migrate_session_data(
            str(tmp_path / "old"), str(tmp_path / "new"), session_id
        )
        assert result is True
        assert (new_dir / session_id / "new_file.txt").read_text() == "new"
        assert not (new_dir / session_id / "stale.txt").exists()


class TestOpenCodeBackend:
    """Tests for OpenCodeBackend."""

    def setup_method(self):
        self.backend = OpenCodeBackend()

    def test_name(self):
        assert self.backend.name == "opencode"

    def test_display_name(self):
        assert self.backend.display_name == "OpenCode"

    def test_binary_name(self):
        assert self.backend.binary_name == "opencode"

    def test_env_vars_to_unset_empty(self):
        assert self.backend.env_vars_to_unset == []

    def test_install_instructions_not_empty(self):
        instructions = self.backend.install_instructions()
        assert len(instructions) > 0
        assert any("opencode" in line.lower() for line in instructions)

    def test_build_launch_command_new_session(self):
        cmd = self.backend.build_launch_command("sess", "abc-123", resume=False)
        assert cmd == "opencode"

    def test_build_launch_command_resume(self):
        cmd = self.backend.build_launch_command("sess", "abc-123", resume=True)
        # OpenCode manages sessions internally; no session flags needed
        assert cmd == "opencode"

    def test_project_dir_is_none(self):
        result = self.backend.project_dir("/some/path")
        assert result is None

    def test_migrate_session_data_returns_false(self):
        result = self.backend.migrate_session_data("/old", "/new", "some-id")
        assert result is False

    @patch("shutil.which", return_value="/usr/local/bin/opencode")
    def test_check_installed_true(self, mock_which):
        assert self.backend.check_installed() is True

    @patch("shutil.which", return_value=None)
    def test_check_installed_false(self, mock_which):
        assert self.backend.check_installed() is False

    def test_is_backend_protocol(self):
        assert isinstance(self.backend, Backend)


class TestBackendRegistry:
    """Tests for the backend registry functions."""

    def test_get_backend_claude(self):
        backend = get_backend("claude")
        assert isinstance(backend, ClaudeCodeBackend)

    def test_get_backend_opencode(self):
        backend = get_backend("opencode")
        assert isinstance(backend, OpenCodeBackend)

    def test_get_backend_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("nonexistent")

    def test_get_available_backends(self):
        backends = get_available_backends()
        assert "claude" in backends
        assert "opencode" in backends

    def test_get_default_backend(self):
        backend = get_default_backend()
        assert backend.name == "claude"


class TestBuildLaunchCommand:
    """Tests for the build_launch_command function in session_ops."""

    def test_claude_backend_produces_correct_command(self):
        from ccmux.session_ops import build_launch_command

        backend = ClaudeCodeBackend()
        cmd = build_launch_command("my-sess", "/tmp/path", "abc-123", backend)
        assert "export CCMUX_SESSION=my-sess" in cmd
        assert "unset CLAUDECODE" in cmd
        assert "claude --session-id abc-123" in cmd
        assert "while true; do $SHELL; done" in cmd

    def test_opencode_backend_produces_correct_command(self):
        from ccmux.session_ops import build_launch_command

        backend = OpenCodeBackend()
        cmd = build_launch_command("my-sess", "/tmp/path", "abc-123", backend)
        assert "export CCMUX_SESSION=my-sess" in cmd
        # OpenCode has no env vars to unset
        assert "unset" not in cmd
        assert "opencode" in cmd
        assert "while true; do $SHELL; done" in cmd

    def test_opencode_resume_command(self):
        from ccmux.session_ops import build_launch_command

        backend = OpenCodeBackend()
        cmd = build_launch_command(
            "my-sess", "/tmp/path", "abc-123", backend, resume=True
        )
        # OpenCode manages sessions internally; same command for new and resume
        assert "opencode" in cmd

    def test_backward_compat_build_claude_command(self):
        """build_claude_command still works as a backward-compatible wrapper."""
        from ccmux.session_ops import build_claude_command

        cmd = build_claude_command("sess", "/p", "id-1")
        assert "claude --session-id id-1" in cmd
        assert "export CCMUX_SESSION=sess" in cmd
