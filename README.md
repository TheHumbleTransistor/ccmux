# ccmux

<p align="center">
  <img src="docs/demo.png" alt="ccmux demo" width="800">
</p>

A streamlined terminal-UI for juggling concurrent Claude Code sessions.

## Features

- **Visual sidebar** — see all sessions at a glance; red highlights tell you instantly when Claude needs your attention
- **CLI session management** — create, list, activate, remove sessions from the terminal
- **Git worktree isolation** — spin up duplicate sessions on isolated branches; use  `ccmux.toml` files to add additional steps when spinning up worktrees, such as setting up untracked build dependencies 

## Prerequisites

Before installing ccmux, make sure you have:

1. **tmux** — terminal multiplexer
   ```bash
   # Ubuntu/Debian
   sudo apt install tmux
   # macOS
   brew install tmux
   ```

2. **Claude Code** — Anthropic's CLI for Claude
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
   See [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code) for details.

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

## Sidebar

| Action | Effect |
|--------|--------|
| Click a session | Switch to it |
| Double-click a session | Edit its note |
| Click a repo header | Collapse or expand the group and select it (highlight blinks, clears after 10 s idle) |
| `↑` / `↓` | Move the selected group up or down |
| `←` / `→` | Collapse / expand the selected group |
| `Esc` | Clear the selection |
| `+` banner (bottom) | Open a repo from your workspace directories, clone a URL, or start a new project |

Group order and collapsed state are remembered across restarts.

## Commands

| Command | Description |
|---------|-------------|
| *(default)* | Auto-attach to existing session or create one |
| `new [PATH]` | Create a new session (add `-w` for worktree, `--init` to create a new repo at PATH) |
| `list` | List all sessions with status and branch info |
| `clone URL` | Clone a repo into a workspace directory (`--into DIR`) and create a session |
| `attach` | Attach to the ccmux tmux session |
| `activate [NAME]` | Reopen Claude Code in a session's tmux window, continuing its most recent conversation |
| `deactivate [NAME]` | Close tmux window (keeps session) |
| `remove [NAME]` | Permanently delete a session |
| `rename OLD NEW` | Rename a session |
| `kill` | Kill entire ccmux session |
| `which` | Print current session name (useful for scripting) |
| `detach` | Detach from tmux |
| `reload` | Restart the sidebar and reapply tmux hooks in place after upgrading ccmux |

## Workspace Directories

The sidebar's `+` button looks for repositories one level under your
workspace directories. Set them in `~/.ccmux/config.toml`:

```toml
[sidebar]
workspace_dirs = ["~/work", "~/Git_Repos"]
```

Without this setting, the parent directories of repos that already have sessions
are searched. `ccmux clone` uses the same list when `--into` is omitted and exactly
one directory is configured.

## Worktree Configuration

Drop a `ccmux.toml` in your repo root to run commands after worktree creation:

```toml
[worktree]
post_create = [
    "ln -s $CCMUX_REPO_ROOT/node_modules $CCMUX_INSTANCE_PATH/node_modules",
    "cp $CCMUX_REPO_ROOT/.env $CCMUX_INSTANCE_PATH/.env",
]
```

Commands run inside the new worktree with these environment variables:

| Variable | Description |
|----------|-------------|
| `CCMUX_REPO_ROOT` | Absolute path to the main repository |
| `CCMUX_INSTANCE_PATH` | Absolute path to the new worktree |
| `CCMUX_INSTANCE_NAME` | Name of the new instance |
| `CCMUX_SESSION` | ccmux tmux session name |

## Contributing

```bash
git clone git@github.com:TheHumbleTransistor/ccmux.git
cd ccmux
pip install -e ".[dev]"
pytest tests/ -v
```

PRs welcome — open an issue first for large changes.

## License

MIT — see [LICENSE](LICENSE)
