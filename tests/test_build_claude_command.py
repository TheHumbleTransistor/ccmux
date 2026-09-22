from ccmux.session_ops import build_agent_command

# Common defaults for repo_root/session_path used across tests
_REPO = "/repo"
_PATH = "/repo"


class TestDefaultAgentCommand:
    """Tests for the default 'claude' agent command."""

    def test_new_session_runs_plain_claude(self):
        cmd = build_agent_command("my-session", repo_root=_REPO, session_path=_PATH, resume=False)
        assert "unset CLAUDECODE; claude; while true" in cmd
        assert "--continue" not in cmd
        assert "--session-id" not in cmd
        assert "--resume" not in cmd

    def test_resume_continues_most_recent_conversation(self):
        cmd = build_agent_command("my-session", repo_root=_REPO, session_path=_PATH, resume=True)
        assert "claude --continue || claude; while true" in cmd
        assert "--session-id" not in cmd
        assert "--resume" not in cmd

    def test_default_is_not_resume(self):
        cmd = build_agent_command("my-session", repo_root=_REPO, session_path=_PATH)
        assert "--continue" not in cmd
        assert "CCMUX_SESSION_RESUMING=0" in cmd


class TestCustomAgentCommand:
    """Tests for custom (non-claude) agent commands."""

    def test_custom_command_no_flags_appended(self):
        cmd = build_agent_command("sess", repo_root=_REPO, session_path=_PATH, agent_launch="aider")
        assert "aider" in cmd
        assert "--continue" not in cmd
        assert "--session-id" not in cmd
        assert "--resume" not in cmd

    def test_custom_command_resume_uses_same_command(self):
        """Custom commands are the same for new and resume — CCMUX_SESSION_RESUMING differentiates."""
        cmd = build_agent_command("sess", repo_root=_REPO, session_path=_PATH, agent_launch="aider", resume=True)
        assert "aider" in cmd
        assert "--continue" not in cmd
        assert "CCMUX_SESSION_RESUMING=1" in cmd

    def test_custom_command_new_session_resuming_is_zero(self):
        cmd = build_agent_command("sess", repo_root=_REPO, session_path=_PATH, agent_launch="aider", resume=False)
        assert "CCMUX_SESSION_RESUMING=0" in cmd


class TestEnvVarsAndShellLoop:
    """Tests for environment variables and shell loop in command output."""

    def test_agent_session_id_not_exported(self):
        for launch in ("claude", "aider"):
            cmd = build_agent_command("sess", repo_root=_REPO, session_path=_PATH, agent_launch=launch)
            assert "CCMUX_AGENT_SESSION_ID" not in cmd

    def test_ccmux_session_env_var(self):
        cmd = build_agent_command("my-sess", repo_root=_REPO, session_path=_PATH)
        assert "export CCMUX_SESSION=my-sess" in cmd

    def test_repo_root_env_var_exported(self):
        cmd = build_agent_command("sess", repo_root="/my/repo", session_path="/my/repo")
        assert "export CCMUX_REPO_ROOT=/my/repo" in cmd

    def test_session_relative_dir_exported(self):
        cmd = build_agent_command("sess", repo_root="/repo", session_path="/repo/.worktrees/sess")
        assert "export CCMUX_SESSION_RELATIVE_DIR=.worktrees/sess" in cmd

    def test_session_relative_dir_dot_for_main_repo(self):
        cmd = build_agent_command("sess", repo_root="/repo", session_path="/repo")
        assert "export CCMUX_SESSION_RELATIVE_DIR=." in cmd

    def test_command_sets_env_and_shell_loop(self):
        cmd = build_agent_command("sess", repo_root=_REPO, session_path=_PATH)
        assert "export CCMUX_SESSION=sess" in cmd
        assert "unset CLAUDECODE" in cmd
        assert "while true; do $SHELL; done" in cmd
