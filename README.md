# Claude Code Worktrees (ccwt)

A Python CLI for managing multiple Claude Code instances using git worktrees and tmux.

## Features

- Create isolated worktrees with Claude Code in one command
- Track worktrees across sessions with persistent state
- Manage multiple repositories simultaneously
- Rich terminal interface with status indicators

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Create a worktree with a random name
ccwt new

# Create a worktree with a specific name
ccwt new feature-name

# List all worktrees
ccwt list

# Show current worktree info
ccwt which

# Attach to tmux session
ccwt attach

# Remove a worktree
ccwt remove feature-name
```

## Commands

### `ccwt new [NAME]`
Create a new git worktree and launch Claude Code in a tmux window.

Options:
- `--session` - Tmux session name (default: `ccwt`)

### `ccwt list`
List all worktrees with status, branch, and tmux window information.

### `ccwt which`
Show which worktree the current tmux window is associated with.

### `ccwt attach`
Attach to a tmux session.

Options:
- `--session` - ccwt session name (default: `ccwt`)

### `ccwt activate [NAME]`
Reopen Claude Code in a worktree's tmux window. Omit NAME to activate all inactive worktrees.

Options:
- `--session` - ccwt session name (default: `ccwt`)
- `--no-confirm` - Skip confirmation prompt

### `ccwt deactivate [NAME]`
Close tmux window without removing the worktree. Omit NAME to deactivate all active worktrees.

Options:
- `--session` - ccwt session name (default: `ccwt`)
- `--no-confirm` - Skip confirmation prompt

### `ccwt remove [NAME]`
Permanently delete a worktree. Omit NAME to remove all worktrees.

Options:
- `--session` - ccwt session name (default: `ccwt`)
- `--no-confirm` - Skip confirmation prompt

## How It Works

- Worktrees are created in `.worktrees/<name>` in detached HEAD state
- State is tracked in `~/.ccwt/state.json`
- Tmux session/window IDs are used for rename-resilient tracking
- Each worktree gets its own tmux window in the specified session

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## License

MIT
