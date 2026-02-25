from ccmux.session_ops import build_claude_command


def test_new_session_uses_session_id():
    cmd = build_claude_command("my-session", "/tmp/path", "abc-123", resume=False)
    assert "--session-id abc-123" in cmd
    assert "--resume" not in cmd


def test_resume_uses_resume_flag():
    cmd = build_claude_command("my-session", "/tmp/path", "abc-123", resume=True)
    assert "--resume abc-123" in cmd
    assert "--session-id" not in cmd


def test_default_is_not_resume():
    cmd = build_claude_command("my-session", "/tmp/path", "abc-123")
    assert "--session-id abc-123" in cmd


def test_command_sets_env_and_shell_loop():
    cmd = build_claude_command("sess", "/p", "id-1")
    assert "export CCMUX_SESSION=sess" in cmd
    assert "unset CLAUDECODE" in cmd
    assert "while true; do $SHELL; done" in cmd
