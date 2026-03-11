from ccmux.session_ops import build_agent_command


class TestDefaultAgentCommand:
    """Tests for the default 'claude' agent command with built-in session management."""

    def test_new_session_uses_session_id(self):
        cmd = build_agent_command("my-session", "abc-123", resume=False)
        assert "claude --session-id abc-123" in cmd
        assert "--resume" not in cmd

    def test_resume_uses_resume_flag(self):
        cmd = build_agent_command("my-session", "abc-123", resume=True)
        assert "claude --resume abc-123" in cmd
        assert "--session-id" not in cmd

    def test_resume_falls_back_to_new_session(self):
        cmd = build_agent_command("my-session", "abc-123", resume=True)
        assert "claude --resume abc-123 || claude" in cmd

    def test_default_is_not_resume(self):
        cmd = build_agent_command("my-session", "abc-123")
        assert "claude --session-id abc-123" in cmd


class TestCustomAgentCommand:
    """Tests for custom (non-claude) agent commands."""

    def test_custom_command_no_flags_appended(self):
        cmd = build_agent_command("sess", "id-1", agent_command="aider")
        assert "aider" in cmd
        assert "--session-id" not in cmd
        assert "--resume" not in cmd

    def test_custom_command_no_resume_command_uses_command(self):
        """When resume_command is None, uses command for resume too."""
        cmd = build_agent_command("sess", "id-1", agent_command="aider", resume=True)
        assert "aider" in cmd
        assert "--resume" not in cmd

    def test_custom_command_with_resume_command(self):
        """When resuming with resume_command set, uses resume_command."""
        cmd = build_agent_command(
            "sess", "id-1",
            agent_command="my-agent --new $CCMUX_AGENT_SESSION_ID",
            resume_command="my-agent --resume $CCMUX_AGENT_SESSION_ID",
            resume=True,
        )
        assert "my-agent --resume $CCMUX_AGENT_SESSION_ID" in cmd
        assert "my-agent --new" not in cmd

    def test_custom_command_new_ignores_resume_command(self):
        """New session always uses command, never resume_command."""
        cmd = build_agent_command(
            "sess", "id-1",
            agent_command="my-agent --new",
            resume_command="my-agent --resume",
            resume=False,
        )
        assert "my-agent --new" in cmd
        assert "my-agent --resume" not in cmd


class TestEnvVarsAndShellLoop:
    """Tests for environment variables and shell loop in command output."""

    def test_session_id_env_var_always_exported_default(self):
        cmd = build_agent_command("sess", "id-1")
        assert "export CCMUX_AGENT_SESSION_ID=id-1" in cmd

    def test_session_id_env_var_always_exported_custom(self):
        cmd = build_agent_command("sess", "id-1", agent_command="aider")
        assert "export CCMUX_AGENT_SESSION_ID=id-1" in cmd

    def test_ccmux_session_env_var(self):
        cmd = build_agent_command("my-sess", "id-1")
        assert "export CCMUX_SESSION=my-sess" in cmd

    def test_repo_root_env_var_exported(self):
        cmd = build_agent_command("sess", "id-1", repo_root="/my/repo")
        assert "export CCMUX_REPO_ROOT=/my/repo" in cmd

    def test_command_sets_env_and_shell_loop(self):
        cmd = build_agent_command("sess", "id-1")
        assert "export CCMUX_SESSION=sess" in cmd
        assert "unset CLAUDECODE" in cmd
        assert "while true; do $SHELL; done" in cmd
