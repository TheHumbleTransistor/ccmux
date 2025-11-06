# Claude Code Multiplexer (ccmux)

A Python CLI for managing multiple Claude Code instances using git repositories and tmux.

## Features

- Create Claude Code instances in main repository or isolated worktrees
- Track instances across sessions with persistent state
- Manage multiple repositories and instances simultaneously
- Rich terminal interface with status indicators

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Create an instance in main repo with a random name
ccmux new

# Create a worktree instance with a specific name
ccmux new feature-name -w

# List all instances
ccmux list

# Show current instance info
ccmux which

# Attach to tmux session
ccmux attach

# Remove an instance
ccmux remove feature-name
```

## Commands

### `ccmux new [NAME]`
Create a new Claude Code instance in the main repo or as a git worktree.

Options:
- `--session` - Tmux session name (default: `ccmux`)
- `-w, --worktree` - Create instance as a git worktree

### `ccmux list`
List all instances with status, type, branch, and tmux window information.

### `ccmux which`
Show which instance the current tmux window is associated with.

### `ccmux attach`
Attach to a tmux session.

Options:
- `--session` - ccmux session name (default: `ccmux`)

### `ccmux activate [NAME]`
Reopen Claude Code in an instance's tmux window. Omit NAME to activate all inactive instances.

Options:
- `--session` - ccmux session name (default: `ccmux`)
- `--no-confirm` - Skip confirmation prompt

### `ccmux deactivate [NAME]`
Close tmux window without removing the instance. Omit NAME to deactivate all active instances.

Options:
- `--session` - ccmux session name (default: `ccmux`)
- `--no-confirm` - Skip confirmation prompt

### `ccmux remove [NAME]`
Permanently delete an instance. Omit NAME to remove all instances.

Options:
- `--session` - ccmux session name (default: `ccmux`)
- `--no-confirm` - Skip confirmation prompt

## How It Works

- Instances can use the main repository or isolated worktrees
- Worktree instances are created in `.worktrees/<name>` in detached HEAD state
- State is tracked in `~/.ccmux/state.json`
- Tmux session/window IDs are used for rename-resilient tracking
- Each instance gets its own tmux window in the specified session

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## License

MIT
