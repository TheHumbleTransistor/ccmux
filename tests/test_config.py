"""Tests for ccmux.config — config accessors and post_create command execution."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from ccmux.config import (
    CommandEvent,
    get_agent_command,
    get_agent_resume_command,
    get_bash_command,
    run_post_create_commands,
    run_repo_init_commands,
    run_session_post_create_commands,
)


def _write_config(tmp_path: Path, toml_content: str) -> Path:
    """Write a ccmux.toml file and return the repo root path."""
    config_file = tmp_path / "ccmux.toml"
    config_file.write_text(toml_content)
    return tmp_path


class TestGetAgentCommand:
    """Tests for get_agent_command config accessor."""

    def test_default_when_no_config(self, tmp_path):
        assert get_agent_command(tmp_path) == "claude"

    def test_custom_command(self, tmp_path):
        _write_config(tmp_path, '[agent]\ncommand = "docker exec -it sandbox claude"\n')
        assert get_agent_command(tmp_path) == "docker exec -it sandbox claude"

    def test_default_when_no_agent_section(self, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = []\n')
        assert get_agent_command(tmp_path) == "claude"


class TestGetAgentResumeCommand:
    """Tests for get_agent_resume_command config accessor."""

    def test_default_when_no_config(self, tmp_path):
        assert get_agent_resume_command(tmp_path) is None

    def test_default_when_no_resume_command(self, tmp_path):
        _write_config(tmp_path, '[agent]\ncommand = "claude"\n')
        assert get_agent_resume_command(tmp_path) is None

    def test_custom_resume_command(self, tmp_path):
        _write_config(tmp_path, '[agent]\nresume_command = "claude --resume $CCMUX_AGENT_SESSION_ID"\n')
        assert get_agent_resume_command(tmp_path) == "claude --resume $CCMUX_AGENT_SESSION_ID"


class TestGetBashCommand:
    """Tests for get_bash_command config accessor."""

    def test_default_when_no_config(self, tmp_path):
        assert get_bash_command(tmp_path) == "$SHELL"

    def test_custom_command(self, tmp_path):
        _write_config(tmp_path, '[bash]\ncommand = "docker exec -it sandbox bash"\n')
        assert get_bash_command(tmp_path) == "docker exec -it sandbox bash"

    def test_default_when_no_bash_section(self, tmp_path):
        _write_config(tmp_path, '[agent]\ncommand = "claude"\n')
        assert get_bash_command(tmp_path) == "$SHELL"


class TestRunPostCreateCommandsNoOp:
    """Cases where the generator should yield nothing."""

    def test_no_config_file(self, tmp_path):
        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))
        assert events == []

    def test_empty_post_create_list(self, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = []\n')
        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))
        assert events == []

    def test_no_worktree_section(self, tmp_path):
        _write_config(tmp_path, '[other]\nkey = "value"\n')
        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))
        assert events == []


class TestBashExecutable:
    """Core regression test for issue #56."""

    @patch("ccmux.config.subprocess.Popen")
    def test_bash_executable_used(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["echo hi"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))

        mock_popen.assert_called_once()
        kwargs = mock_popen.call_args[1]
        assert kwargs["executable"] == "/bin/bash"
        assert kwargs["shell"] is True


class TestCommandEvents:
    """Verify event sequences from the generator."""

    @patch("ccmux.config.subprocess.Popen")
    def test_successful_command_events(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["echo hello"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["hello\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))

        assert len(events) == 3
        assert events[0] == CommandEvent(cmd="echo hello", event_type="start")
        assert events[1] == CommandEvent(cmd="echo hello", event_type="stdout", data="hello")
        assert events[2] == CommandEvent(cmd="echo hello", event_type="success")

    @patch("ccmux.config.subprocess.Popen")
    def test_failed_command_events(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["false"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))

        assert events[-1].event_type == "failure"
        assert events[-1].returncode == 1

    @patch("ccmux.config.subprocess.Popen")
    def test_exception_yields_error_event(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["boom"]\n')
        mock_popen.side_effect = OSError("no such file")

        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))

        assert len(events) == 2
        assert events[0].event_type == "start"
        assert events[1].event_type == "error"
        assert "no such file" in events[1].data

    @patch("ccmux.config.subprocess.Popen")
    def test_multiple_commands_sequential(self, mock_popen, tmp_path):
        _write_config(
            tmp_path,
            '[worktree]\npost_create = ["echo a", "echo b"]\n',
        )
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        events = list(run_post_create_commands(tmp_path, tmp_path / "wt", "sess"))

        start_events = [e for e in events if e.event_type == "start"]
        assert len(start_events) == 2
        assert start_events[0].cmd == "echo a"
        assert start_events[1].cmd == "echo b"


class TestEnvironmentAndCwd:
    """Verify env vars and working directory passed to Popen."""

    @patch("ccmux.config.subprocess.Popen")
    def test_environment_variables_set(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["true"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        session_path = tmp_path / "wt"
        list(run_post_create_commands(tmp_path, session_path, "my-session"))

        env = mock_popen.call_args[1]["env"]
        assert env["CCMUX_REPO_ROOT"] == str(tmp_path)
        assert env["CCMUX_SESSION_PATH"] == str(session_path)
        assert env["CCMUX_SESSION_NAME"] == "my-session"

    @patch("ccmux.config.subprocess.Popen")
    def test_cwd_is_session_path(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["true"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        session_path = tmp_path / "wt"
        list(run_post_create_commands(tmp_path, session_path, "sess"))

        assert mock_popen.call_args[1]["cwd"] == str(session_path)


class TestRunSessionPostCreateCommands:
    """Tests for [session].post_create command execution."""

    def test_no_config_file(self, tmp_path):
        events = list(run_session_post_create_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    def test_empty_post_create_list(self, tmp_path):
        _write_config(tmp_path, '[session]\npost_create = []\n')
        events = list(run_session_post_create_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    def test_no_session_section(self, tmp_path):
        _write_config(tmp_path, '[worktree]\npost_create = ["echo wt"]\n')
        events = list(run_session_post_create_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    @patch("ccmux.config.subprocess.Popen")
    def test_runs_session_commands(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[session]\npost_create = ["echo hello"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["hello\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        events = list(run_session_post_create_commands(tmp_path, tmp_path, "sess"))

        assert len(events) == 3
        assert events[0] == CommandEvent(cmd="echo hello", event_type="start")
        assert events[1] == CommandEvent(cmd="echo hello", event_type="stdout", data="hello")
        assert events[2] == CommandEvent(cmd="echo hello", event_type="success")

    @patch("ccmux.config.subprocess.Popen")
    def test_does_not_run_worktree_commands(self, mock_popen, tmp_path):
        """[session].post_create should not pick up [worktree].post_create."""
        _write_config(tmp_path, '[worktree]\npost_create = ["echo wt"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        events = list(run_session_post_create_commands(tmp_path, tmp_path, "sess"))
        assert events == []
        mock_popen.assert_not_called()

    @patch("ccmux.config.subprocess.Popen")
    def test_env_vars_set(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[session]\npost_create = ["true"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        session_path = tmp_path / "work"
        list(run_session_post_create_commands(tmp_path, session_path, "my-sess"))

        env = mock_popen.call_args[1]["env"]
        assert env["CCMUX_REPO_ROOT"] == str(tmp_path)
        assert env["CCMUX_SESSION_PATH"] == str(session_path)
        assert env["CCMUX_SESSION_NAME"] == "my-sess"


class TestDisplayIntegration:
    """Tests for _run_post_create_with_display in session_ops."""

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_post_create_commands")
    def test_display_prints_command_and_output(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_post_create_with_display

        mock_gen.return_value = iter([
            CommandEvent(cmd="echo hi", event_type="start"),
            CommandEvent(cmd="echo hi", event_type="stdout", data="hi"),
            CommandEvent(cmd="echo hi", event_type="success"),
        ])

        _run_post_create_with_display(Path("/repo"), Path("/wt"), "sess")

        printed = [str(c) for c in mock_console.print.call_args_list]
        joined = " ".join(printed)
        assert "post_create" in joined
        assert "echo hi" in joined
        assert "OK" in joined

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_post_create_commands")
    def test_display_shows_failure_warning(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_post_create_with_display

        mock_gen.return_value = iter([
            CommandEvent(cmd="bad", event_type="start"),
            CommandEvent(cmd="bad", event_type="failure", returncode=2),
        ])

        _run_post_create_with_display(Path("/repo"), Path("/wt"), "sess")

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "Failed" in printed
        assert "hook(s) failed" in printed

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_post_create_commands")
    def test_display_noop_when_no_commands(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_post_create_with_display

        mock_gen.return_value = iter([])

        _run_post_create_with_display(Path("/repo"), Path("/wt"), "sess")

        mock_console.print.assert_not_called()


class TestSessionDisplayIntegration:
    """Tests for _run_session_post_create_with_display in session_ops."""

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_session_post_create_commands")
    def test_display_prints_session_hooks(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_session_post_create_with_display

        mock_gen.return_value = iter([
            CommandEvent(cmd="echo setup", event_type="start"),
            CommandEvent(cmd="echo setup", event_type="success"),
        ])

        _run_session_post_create_with_display(Path("/repo"), Path("/wt"), "sess")

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "session post_create" in printed
        assert "echo setup" in printed

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_session_post_create_commands")
    def test_display_noop_when_no_commands(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_session_post_create_with_display

        mock_gen.return_value = iter([])

        _run_session_post_create_with_display(Path("/repo"), Path("/wt"), "sess")

        mock_console.print.assert_not_called()


class TestRunRepoInitCommands:
    """Tests for [repo].init command execution."""

    def test_no_config_file(self, tmp_path):
        events = list(run_repo_init_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    def test_empty_init_list(self, tmp_path):
        _write_config(tmp_path, '[repo]\ninit = []\n')
        events = list(run_repo_init_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    def test_no_repo_section(self, tmp_path):
        _write_config(tmp_path, '[session]\npost_create = ["echo hi"]\n')
        events = list(run_repo_init_commands(tmp_path, tmp_path, "sess"))
        assert events == []

    @patch("ccmux.config.subprocess.Popen")
    def test_runs_init_commands(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[repo]\ninit = ["npm install"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["added 100 packages\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        events = list(run_repo_init_commands(tmp_path, tmp_path, "sess"))

        assert len(events) == 3
        assert events[0] == CommandEvent(cmd="npm install", event_type="start")
        assert events[1] == CommandEvent(cmd="npm install", event_type="stdout", data="added 100 packages")
        assert events[2] == CommandEvent(cmd="npm install", event_type="success")

    @patch("ccmux.config.subprocess.Popen")
    def test_does_not_run_session_or_worktree_commands(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[session]\npost_create = ["echo session"]\n[worktree]\npost_create = ["echo wt"]\n')
        events = list(run_repo_init_commands(tmp_path, tmp_path, "sess"))
        assert events == []
        mock_popen.assert_not_called()

    @patch("ccmux.config.subprocess.Popen")
    def test_env_vars_set(self, mock_popen, tmp_path):
        _write_config(tmp_path, '[repo]\ninit = ["true"]\n')
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        session_path = tmp_path / "work"
        list(run_repo_init_commands(tmp_path, session_path, "my-sess"))

        env = mock_popen.call_args[1]["env"]
        assert env["CCMUX_REPO_ROOT"] == str(tmp_path)
        assert env["CCMUX_SESSION_PATH"] == str(session_path)
        assert env["CCMUX_SESSION_NAME"] == "my-sess"


class TestRepoInitDisplayIntegration:
    """Tests for _run_repo_init_with_display in session_ops."""

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_repo_init_commands")
    def test_display_prints_repo_init_hooks(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_repo_init_with_display

        mock_gen.return_value = iter([
            CommandEvent(cmd="npm install", event_type="start"),
            CommandEvent(cmd="npm install", event_type="success"),
        ])

        _run_repo_init_with_display(Path("/repo"), Path("/wt"), "sess")

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "repo init" in printed
        assert "npm install" in printed

    @patch("ccmux.session_ops.console")
    @patch("ccmux.session_ops.run_repo_init_commands")
    def test_display_noop_when_no_commands(self, mock_gen, mock_console):
        from ccmux.session_ops import _run_repo_init_with_display

        mock_gen.return_value = iter([])

        _run_repo_init_with_display(Path("/repo"), Path("/wt"), "sess")

        mock_console.print.assert_not_called()


class TestIsFirstSessionForRepo:
    """Tests for _is_first_session_for_repo."""

    @patch("ccmux.session_ops.state")
    def test_true_when_no_sessions(self, mock_state):
        from ccmux.session_ops import _is_first_session_for_repo

        mock_state.get_all_sessions.return_value = []
        assert _is_first_session_for_repo(Path("/repo")) is True

    @patch("ccmux.session_ops.state")
    def test_true_when_no_sessions_for_this_repo(self, mock_state):
        from ccmux.session_ops import _is_first_session_for_repo

        other_sess = MagicMock()
        other_sess.repo_path = "/other/repo"
        mock_state.get_all_sessions.return_value = [other_sess]
        assert _is_first_session_for_repo(Path("/repo")) is True

    @patch("ccmux.session_ops.state")
    def test_false_when_session_exists_for_repo(self, mock_state):
        from ccmux.session_ops import _is_first_session_for_repo

        existing = MagicMock()
        existing.repo_path = "/repo"
        mock_state.get_all_sessions.return_value = [existing]
        assert _is_first_session_for_repo(Path("/repo")) is False
