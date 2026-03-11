from ccmux.session_ops import build_agent_command

# Common defaults for repo_root/session_path used across tests
_REPO = "/repo"
_PATH = "/repo"


class TestDefaultAgentCommand:
    """Tests for the default 'claude' agent command with built-in session management."""

    def test_new_session_uses_session_id(self):
        cmd = build_agent_command("my-session", "abc-123", repo_root=_REPO, session_path=_PATH, resume=False)
        assert "claude --session-id abc-123" in cmd
        assert "--resume" not in cmd

    def test_resume_uses_resume_flag(self):
        cmd = build_agent_command("my-session", "abc-123", repo_root=_REPO, session_path=_PATH, resume=True)
        assert "claude --resume abc-123" in cmd
        assert "--session-id" not in cmd

    def test_resume_falls_back_to_new_session(self):
        cmd = build_agent_command("my-session", "abc-123", repo_root=_REPO, session_path=_PATH, resume=True)
        assert "claude --resume abc-123 || claude" in cmd

    def test_default_is_not_resume(self):
        cmd = build_agent_command("my-session", "abc-123", repo_root=_REPO, session_path=_PATH)
        assert "claude --session-id abc-123" in cmd


class TestCustomAgentCommand:
    """Tests for custom (non-claude) agent commands."""

    def test_custom_command_no_flags_appended(self):
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH, agent_launch="aider")
        assert "aider" in cmd
        assert "--session-id" not in cmd
        assert "--resume" not in cmd

    def test_custom_command_resume_uses_same_command(self):
        """Custom commands are the same for new and resume — CCMUX_SESSION_RESUMING differentiates."""
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH, agent_launch="aider", resume=True)
        assert "aider" in cmd
        assert "--resume" not in cmd
        assert "CCMUX_SESSION_RESUMING=1" in cmd

    def test_custom_command_new_session_resuming_is_zero(self):
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH, agent_launch="aider", resume=False)
        assert "CCMUX_SESSION_RESUMING=0" in cmd


class TestEnvVarsAndShellLoop:
    """Tests for environment variables and shell loop in command output."""

    def test_session_id_env_var_always_exported_default(self):
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH)
        assert "export CCMUX_AGENT_SESSION_ID=id-1" in cmd

    def test_session_id_env_var_always_exported_custom(self):
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH, agent_launch="aider")
        assert "export CCMUX_AGENT_SESSION_ID=id-1" in cmd

    def test_ccmux_session_env_var(self):
        cmd = build_agent_command("my-sess", "id-1", repo_root=_REPO, session_path=_PATH)
        assert "export CCMUX_SESSION=my-sess" in cmd

    def test_repo_root_env_var_exported(self):
        cmd = build_agent_command("sess", "id-1", repo_root="/my/repo", session_path="/my/repo")
        assert "export CCMUX_REPO_ROOT=/my/repo" in cmd

    def test_session_relative_dir_exported(self):
        cmd = build_agent_command("sess", "id-1", repo_root="/repo", session_path="/repo/.worktrees/sess")
        assert "export CCMUX_SESSION_RELATIVE_DIR=.worktrees/sess" in cmd

    def test_session_relative_dir_dot_for_main_repo(self):
        cmd = build_agent_command("sess", "id-1", repo_root="/repo", session_path="/repo")
        assert "export CCMUX_SESSION_RELATIVE_DIR=." in cmd

    def test_command_sets_env_and_shell_loop(self):
        cmd = build_agent_command("sess", "id-1", repo_root=_REPO, session_path=_PATH)
        assert "export CCMUX_SESSION=sess" in cmd
        assert "unset CLAUDECODE" in cmd
        assert "while true; do $SHELL; done" in cmd
