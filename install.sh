#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "Claude Code Worktrees - Installation"
echo "========================================"
echo ""

# --- Check dependencies ---
echo "Checking dependencies..."
MISSING_DEPS=()

if ! command -v git &>/dev/null; then
  MISSING_DEPS+=("git")
fi

if ! command -v tmux &>/dev/null; then
  MISSING_DEPS+=("tmux")
fi

if ! command -v claude &>/dev/null; then
  MISSING_DEPS+=("claude")
fi

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
  echo "❌ Missing required dependencies: ${MISSING_DEPS[*]}"
  echo ""
  echo "Please install the missing dependencies:"
  for dep in "${MISSING_DEPS[@]}"; do
    case "$dep" in
      git)
        echo "  - git: https://git-scm.com/downloads"
        ;;
      tmux)
        echo "  - tmux: apt install tmux / brew install tmux"
        ;;
      claude)
        echo "  - claude: npm install -g @anthropic-ai/claude-code"
        ;;
    esac
  done
  exit 1
fi

echo "✓ All dependencies found"
echo ""

# --- Create ~/bin if needed ---
if [[ ! -d "$HOME/bin" ]]; then
  echo "Creating ~/bin directory..."
  mkdir -p "$HOME/bin"
  echo "✓ Created ~/bin"
  echo ""
  echo "⚠️  Note: You may need to add ~/bin to your PATH."
  echo "   Add this to your ~/.bashrc or ~/.zshrc:"
  echo "   export PATH=\"\$HOME/bin:\$PATH\""
  echo ""
fi

# --- Backup existing files ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKED_UP=false

if [[ -f "$HOME/bin/ccwt" ]]; then
  BACKUP_PATH="$HOME/bin/ccwt.backup.$TIMESTAMP"
  cp "$HOME/bin/ccwt" "$BACKUP_PATH"
  echo "✓ Backed up existing ccwt to: $BACKUP_PATH"
  BACKED_UP=true
fi

if [[ -f "$HOME/.tmux.conf" ]]; then
  BACKUP_PATH="$HOME/.tmux.conf.backup.$TIMESTAMP"
  cp "$HOME/.tmux.conf" "$BACKUP_PATH"
  echo "✓ Backed up existing .tmux.conf to: $BACKUP_PATH"
  BACKED_UP=true
fi

if [[ "$BACKED_UP" = true ]]; then
  echo ""
fi

# --- Install files ---
echo "Installing files..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install ccwt
cp "$SCRIPT_DIR/ccwt" "$HOME/bin/ccwt"
chmod +x "$HOME/bin/ccwt"
echo "✓ Installed ccwt to ~/bin/ccwt"

# Install tmux.conf
cp "$SCRIPT_DIR/tmux.conf" "$HOME/.tmux.conf"
echo "✓ Installed tmux.conf to ~/.tmux.conf"

echo ""
echo "========================================"
echo "✓ Installation complete!"
echo "========================================"
echo ""
echo "Usage:"
echo "  ccwt              # Create a worktree with a random animal name"
echo "  ccwt my-feature   # Create a worktree named 'my-feature'"
echo ""
echo "The script will:"
echo "  - Create a git worktree in .worktrees/<name>"
echo "  - Create a branch named <name>"
echo "  - Open a tmux window in the 'claude-cluster' session"
echo "  - Launch Claude Code in that worktree"
echo ""
