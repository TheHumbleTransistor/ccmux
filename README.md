# ccmux

<p align="center">
  <img src="docs/demo.png" alt="ccmux demo" width="800">
</p>

A streamlined terminal-UI for juggling concurrent AI coding sessions.

Supports [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [OpenCode](https://opencode.ai/docs) — run them side-by-side in the same workspace.

## Features

- **Multi-backend support** — use Claude Code, OpenCode, or both in the same workspace
- **Visual sidebar** — see all sessions at a glance; red highlights tell you instantly when a tool needs your attention
- **CLI session management** — create, list, activate, remove sessions from the terminal
- **Git worktree isolation** — spin up duplicate sessions on isolated branches; use `ccmux.toml` files to add additional steps when spinning up worktrees, such as setting up untracked build dependencies

## Prerequisites

Before installing ccmux, make sure you have:

1. **tmux** — terminal multiplexer
   ```bash
   # Ubuntu/Debian
   sudo apt install tmux
   # macOS
   brew install tmux
   ```

2. **At least one supported AI coding tool:**

   - **Claude Code** — Anthropic's CLI for Claude
     ```bash
     npm install -g @anthropic-ai/claude-code
     ```
     See [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code) for details.

   - **OpenCode** — Open-source AI coding assistant
     ```bash
     curl -fsSL https://opencode.ai/install | bash
     # or: npm install -g opencode-ai
     # or: brew install anomalyco/tap/opencode
     ```
     See [OpenCode documentation](https://opencode.ai/docs) for details.

## Installation

```bash
# Recommended
pipx install ccmux

# Or, if you don't use pipx
pip install ccmux
```

## Quick Start

```bash
ccmux             # auto-creates a session for the current directory or attaches to an existing one
ccmux new         # create a new session from the current directory's repo
```

## Commands

| Command | Description |
|---------|-------------|
| *(default)* | Auto-attach to existing session or create one |
| `new [PATH]` | Create a new session (add `-w` for worktree, `-b` for backend) |
| `list` | List all sessions with status and branch info |
| `attach` | Attach to the ccmux tmux session |
| `activate [NAME]` | Reopen the coding tool in a session's tmux window |
| `deactivate [NAME]` | Close tmux window (keeps session) |
| `remove [NAME]` | Permanently delete a session |
| `rename OLD NEW` | Rename a session |
| `kill` | Kill entire ccmux session |
| `which` | Print current session name (useful for scripting) |
| `detach` | Detach from tmux |

## Configuration

Drop a `ccmux.toml` in your repo root to configure ccmux for that project.

### Backend

Set the default AI coding tool for a project:

```toml
[backend]
name = "opencode"   # or "claude" (default)
```

You can also override the backend per-session with the `-b` flag:

```bash
ccmux new -b opencode    # create an OpenCode session
ccmux new -w -b claude   # create a Claude Code worktree session
```

### Worktree Post-Create Hooks

Run commands automatically after worktree creation:

```toml
[worktree]
post_create = [
    "ln -s $CCMUX_REPO_ROOT/node_modules $CCMUX_SESSION_PATH/node_modules",
    "cp $CCMUX_REPO_ROOT/.env $CCMUX_SESSION_PATH/.env",
]
```

Commands run inside the new worktree with these environment variables:

| Variable | Description |
|----------|-------------|
| `CCMUX_REPO_ROOT` | Absolute path to the main repository |
| `CCMUX_SESSION_PATH` | Absolute path to the new worktree |
| `CCMUX_SESSION_NAME` | Name of the new session |
| `CCMUX_SESSION` | ccmux tmux session name |

## Contributing

```bash
git clone git@github.com:TheHumbleTransistor/ccmux.git
cd ccmux
pip install -e ".[dev]"
pytest tests/ -v
```

PRs welcome — open an issue first for large changes.

### Adding a New Backend

ccmux uses a backend system to support different AI coding tools. To add a new one:

1. **Create a class** in `ccmux/backend.py` that implements the `Backend` protocol:

   ```python
   class MyToolBackend:
       @property
       def name(self) -> str:
           return "mytool"              # used in ccmux.toml and -b flag

       @property
       def display_name(self) -> str:
           return "My Tool"             # shown in sidebar and ccmux list

       @property
       def binary_name(self) -> str:
           return "mytool"              # CLI binary checked on PATH

       @property
       def env_vars_to_unset(self) -> list[str]:
           return []                    # env vars to clear before launching

       def check_installed(self) -> bool:
           return shutil.which("mytool") is not None

       def install_instructions(self) -> list[str]:
           return ["Install My Tool:", "  npm install -g mytool"]

       def build_launch_command(self, name, session_id, resume=False) -> str:
           return f"mytool --session {session_id}"

       def project_dir(self, session_path) -> Optional[Path]:
           return None                  # return path if tool uses project-local data

       def migrate_session_data(self, old_path, new_path, session_id) -> bool:
           return False                 # implement if project data needs copying on rename
   ```

2. **Register it** in the `_BACKENDS` dict at the bottom of `ccmux/backend.py`:

   ```python
   _BACKENDS: dict[str, type] = {
       "claude": ClaudeCodeBackend,
       "opencode": OpenCodeBackend,
       "mytool": MyToolBackend,
   }
   ```

3. **Add tests** in `tests/test_backend.py` following the existing pattern.

That's it — `ccmux new -b mytool` and `ccmux.toml` `[backend] name = "mytool"` will work automatically.

## License

MIT — see [LICENSE](LICENSE)
