#!/usr/bin/env bash
set -euo pipefail

# new-cc-wt [name]
# - Run from anywhere inside a git repo.
# - If [name] omitted, generates a random animal name.
# - Creates a new git worktree (.worktrees/<name>) on branch <name>.
# - Opens a tmux window in session 'claude-cluster' named <name> and runs `claude code`.

# --- Find git repo root ---
if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "Error: not inside a git repository." >&2
  exit 1
fi
cd "$REPO_ROOT"

USER_NAME="${1:-}"

# --- Random animal name generator ---
generate_animal_name() {
  local animals=(
    otter lynx fox wolf bear wren robin hawk eagle falcon
    heron swan crane goose duck loon ibis kiwi dingo quokka
    bison yak ibex oryx okapi tapir panda koala wombat
    gecko skink python mamba cobra viper boar mole vole
    puma jaguar leopard tiger lion cheetah serval caracal ocelot
    kudu eland gazelle impala springbok hyena dolphin orca beluga manatee seal walrus penguin
    salmon trout sturgeon carp pike marlin tuna halibut cod
    owl kestrel harrier kite buzzard condor vulture beetle moth ant wasp bee dragonfly mantis
    beaver muskrat hare rabbit pika
  )
  printf "%s\n" "${animals[@]}" | shuf -n 1
}

sanitize() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/^-+|-+$//g; s/-{2,}/-/g'
}

NAME="$USER_NAME"
if [[ -z "$NAME" ]]; then
  for _ in {1..20}; do
    cand="$(sanitize "$(generate_animal_name)")"
    WT_DIR="$REPO_ROOT/.worktrees/$cand"
    if [[ ! -d "$WT_DIR/.git" ]] && ! git show-ref --verify --quiet "refs/heads/$cand"; then
      NAME="$cand"
      break
    fi
  done
  if [[ -z "$NAME" ]]; then
    base="$(sanitize "$(generate_animal_name)")"
    suffix="$(head -c2 /dev/urandom | od -An -t u1 | awk '{printf("%d%d",$1%10,$2%10)}')"
    NAME="${base}-${suffix}"
  fi
else
  NAME="$(sanitize "$NAME")"
fi

WT_DIR="$REPO_ROOT/.worktrees/$NAME"
mkdir -p "$REPO_ROOT/.worktrees"

# --- Create worktree/branch if missing ---
# Check if worktree is already registered
if git worktree list | grep -q "$WT_DIR"; then
  echo "   Worktree already exists, reusing it."
elif git show-ref --verify --quiet "refs/heads/$NAME"; then
  # Branch exists, attach worktree to it
  git worktree add "$WT_DIR" "$NAME"
else
  # Create new branch and worktree
  git worktree add "$WT_DIR" -b "$NAME"
fi

# --- Start/attach tmux session ---
SESSION="claude-cluster"
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux new-session -d -s "$SESSION" -n "home"
fi

echo "▶ Claude Code instance: $NAME"
echo "   Repo root: $REPO_ROOT"
echo "   Worktree:  $WT_DIR"
echo "   Branch:    $NAME"

tmux new-window -t "$SESSION" -n "$NAME" -c "$WT_DIR" "echo 'Launching Claude Code in $WT_DIR (branch $NAME)'; claude || { echo 'Claude Code failed to start. Press enter to close.'; read; }"
tmux select-window -t "$SESSION:$NAME"
tmux attach -t "$SESSION"
