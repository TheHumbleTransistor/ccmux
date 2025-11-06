#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "Claude Code Multiplexer - Installation"
echo "========================================"
echo ""

# --- Check dependencies ---
echo "Checking dependencies..."
MISSING_DEPS=()

if ! command -v python3 &>/dev/null; then
  MISSING_DEPS+=("python3")
fi

if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
  MISSING_DEPS+=("pip")
fi

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
      python3)
        echo "  - python3 (3.8+): https://www.python.org/downloads/"
        ;;
      pip)
        echo "  - pip: https://pip.pypa.io/en/stable/installation/"
        ;;
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

# --- Check Python version ---
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 8 ]]; then
  echo "❌ Python 3.8 or higher is required (found $PYTHON_VERSION)"
  exit 1
fi

echo "✓ Python $PYTHON_VERSION detected"
echo ""

# --- Install Python package ---
echo "Installing ccmux Python package..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use pip or pip3, whichever is available
if command -v pip &>/dev/null; then
  PIP_CMD="pip"
else
  PIP_CMD="pip3"
fi

# Install in editable mode
if "$PIP_CMD" install -e "$SCRIPT_DIR"; then
  echo "✓ Installed ccmux package"
else
  echo "❌ Failed to install ccmux package"
  exit 1
fi
echo ""

# --- Optional: Install tmux.conf ---
echo "tmux configuration"
echo "------------------"
if [[ -f "$HOME/.tmux.conf" ]]; then
  echo "You already have a ~/.tmux.conf file."
  read -p "Do you want to backup and replace it with ccmux's tmux.conf? [y/N] " -n 1 -r
  echo ""
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_PATH="$HOME/.tmux.conf.backup.$TIMESTAMP"
    cp "$HOME/.tmux.conf" "$BACKUP_PATH"
    echo "✓ Backed up existing .tmux.conf to: $BACKUP_PATH"
    cp "$SCRIPT_DIR/tmux.conf" "$HOME/.tmux.conf"
    echo "✓ Installed tmux.conf to ~/.tmux.conf"
  else
    echo "Skipped tmux.conf installation"
    echo "You can manually copy it later: cp $SCRIPT_DIR/tmux.conf ~/.tmux.conf"
  fi
else
  read -p "Install tmux.conf to ~/.tmux.conf? [Y/n] " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    cp "$SCRIPT_DIR/tmux.conf" "$HOME/.tmux.conf"
    echo "✓ Installed tmux.conf to ~/.tmux.conf"
  else
    echo "Skipped tmux.conf installation"
    echo "You can manually copy it later: cp $SCRIPT_DIR/tmux.conf ~/.tmux.conf"
  fi
fi

echo ""
echo "========================================"
echo "✓ Installation complete!"
echo "========================================"
echo ""
echo "Usage:"
echo "  ccmux new             # Create an instance in main repo with a random name"
echo "  ccmux new my-feature  # Create an instance named 'my-feature'"
echo "  ccmux new -w          # Create a worktree instance with a random name"
echo "  ccmux list            # List all instances and their status"
echo "  ccmux attach          # Attach to the tmux session"
echo "  ccmux --help          # Show all available commands"
echo ""
echo "For more information, see: https://github.com/raykamp-tht/claude-code-worktrees"
echo ""
