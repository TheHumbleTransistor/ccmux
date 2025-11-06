# Claude Code Worktrees

A streamlined workflow for running multiple parallel Claude Code instances using git worktrees and tmux.

## Overview

This toolkit provides:

- **`ccwt`** - A script to quickly create git worktrees with isolated Claude Code instances
- **`tmux.conf`** - Tmux configuration optimized for monitoring multiple Claude sessions with activity notifications

## Why Use This?

When working with Claude Code on multiple tasks simultaneously, you want:

1. **Isolation** - Each task in its own worktree and branch
2. **Visibility** - Easy monitoring of which Claude instances need attention
3. **Efficiency** - Quick setup without manual worktree/branch creation

This toolkit solves all three: git worktrees provide isolation, tmux with activity monitoring provides visibility, and the `ccwt` script provides efficiency.

## Prerequisites

- **git** - For worktree management
- **tmux** - For terminal multiplexing
- **claude** - The Claude Code CLI ([installation guide](https://docs.claude.com/))
- **bash** - For running the scripts

## Installation

```bash
git clone git@github.com:raykamp-tht/claude-code-worktrees.git
cd claude-code-worktrees
./install.sh
```

The installer will:
- Check for required dependencies
- Create `~/bin` if it doesn't exist
- Backup any existing `ccwt` or `.tmux.conf` files
- Install `ccwt` to `~/bin/ccwt`
- Install `tmux.conf` to `~/.tmux.conf`

**Note:** Make sure `~/bin` is in your PATH. Add to your `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/bin:$PATH"
```

## Usage

### Basic Usage

From anywhere inside a git repository:

```bash
# Create a worktree with a random animal name
ccwt

# Create a worktree with a specific name
ccwt my-feature
```

This will:
1. Create a new git worktree in `.worktrees/<name>`
2. Create a new branch named `<name>` (or use existing branch if it exists)
3. Create/attach to tmux session `claude-cluster`
4. Open a new tmux window named `<name>`
5. Launch Claude Code in that worktree

### Working with Multiple Instances

```bash
# In your git repo root
ccwt feature-a
# Switch to another tmux window (Ctrl+b, n)
ccwt feature-b
ccwt bugfix-123
```

Now you have three Claude Code instances running in parallel, each in:
- Its own git worktree (`.worktrees/feature-a`, etc.)
- Its own git branch (`feature-a`, etc.)
- Its own tmux window

### Tmux Activity Monitoring

The included tmux configuration provides:
- **Mouse support** - Click to switch windows
- **Activity monitoring** - Windows with output are highlighted in bold yellow
- **Bell notifications** - Windows with bell events are highlighted in red
- **Keyboard shortcuts**:
  - `Ctrl+b, a` - Jump to window with most recent activity
  - `Ctrl+b, C-l` - Clear all activity marks

### Workflow Example

```bash
# Start working on a new feature
ccwt user-auth

# Claude makes progress, you notice another issue
# Switch windows (Ctrl+b, c for new shell, or open another terminal)
ccwt hotfix-login

# While Claude works on hotfix, the user-auth window shows activity
# Press Ctrl+b, a to jump to the active window
```

## How It Works

### The `ccwt` Script

1. **Validates environment** - Ensures you're in a git repo
2. **Generates name** - Uses random animal name if not provided, with collision avoidance
3. **Creates worktree** - Safely creates worktree and branch:
   - If worktree exists: reuses it
   - If branch exists: attaches to it (no reset)
   - Otherwise: creates new branch with `-b` flag
4. **Launches Claude** - Opens tmux window and starts Claude Code
5. **Error handling** - Keeps window open if Claude fails to start

### Git Worktrees Structure

```
my-repo/
├── .git/
├── .worktrees/
│   ├── feature-a/     # Worktree for feature-a branch
│   ├── feature-b/     # Worktree for feature-b branch
│   └── bugfix-123/    # Worktree for bugfix-123 branch
└── [main repo files]
```

Each worktree is a complete checkout of your repository on a different branch.

## Configuration

### Customizing Animal Names

Edit the `animals` array in the `ccwt` script to change the random name pool.

### Customizing Tmux Behavior

Edit `~/.tmux.conf` or add overrides to `~/.tmux.conf.local`:

```bash
# Example: Change activity highlight color
set -g window-status-activity-style "bold,fg=cyan"
```

### Changing Tmux Session Name

By default, worktrees open in a session named `claude-cluster`. To change this, edit the `SESSION` variable in the `ccwt` script:

```bash
SESSION="your-session-name"
```

## Troubleshooting

### "Command not found: ccwt"

Make sure `~/bin` is in your PATH:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### "Claude Code failed to start"

1. Verify Claude is installed: `which claude`
2. Check your authentication: `claude setup-token`
3. Check the error message in the tmux window

### Worktree Already Exists

If you see an error about an existing worktree, you can:
- Use a different name: `ccwt feature-a-v2`
- Remove the old worktree: `git worktree remove .worktrees/<name>`
- Use the existing worktree (script will reuse it)

## License

MIT

## Contributing

This is a personal toolkit, but feel free to fork and customize for your own workflow!
