#!/usr/bin/env bash
# Integration test: launch demo sidebar in tmux, send mouse clicks, verify content.
# Usage: bash tests/test_sidebar_tmux.sh
set -euo pipefail

SESSION="ccmux-sidebar-test-$$"
PASS=0
FAIL=0

cleanup() {
    tmux kill-session -t "$SESSION" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Sidebar tmux integration test ==="

# 1. Start demo sidebar inside a new tmux session
tmux new-session -d -s "$SESSION" -x 40 -y 24 \
    "python -m ccmux.sidebar --demo"
sleep 3  # Wait for Textual to render

# 2. Capture initial pane content
initial=$(tmux capture-pane -t "$SESSION" -p)

check() {
    local label="$1" pattern="$2" content="$3"
    if echo "$content" | grep -q "$pattern"; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label (expected '$pattern')"
        FAIL=$((FAIL + 1))
    fi
}

echo "--- Initial render ---"
check "CCMUX title present" "CCMUX" "$initial"
check "Session header present" "Session:" "$initial"
check "my-project repo present" "my-project" "$initial"
check "other-repo present" "other-repo" "$initial"

# 3. Send mouse click (button 1 press+release at row 8, col 5) via escape sequences
#    MouseDown: \e[M BUTTON COL ROW  (add 32 to each value)
#    MouseUp:   \e[M #   COL ROW
# Row 8, Col 5 => encoded as row=40 col=37
tmux send-keys -t "$SESSION" -l $'\e[M \x25\x28'   # mouse down at col 5, row 8
sleep 0.1
tmux send-keys -t "$SESSION" -l $'\e[M#\x25\x28'   # mouse up at col 5, row 8
sleep 1

# 4. Capture after click
after_click=$(tmux capture-pane -t "$SESSION" -p)

echo "--- After click ---"
check "CCMUX title survives click" "CCMUX" "$after_click"
check "Session header survives click" "Session:" "$after_click"
check "my-project survives click" "my-project" "$after_click"
check "other-repo survives click" "other-repo" "$after_click"

# 5. Send several rapid clicks at different rows
for row_enc in $'\x24' $'\x26' $'\x2a' $'\x2c'; do
    tmux send-keys -t "$SESSION" -l $'\e[M \x25'"$row_enc"
    sleep 0.05
    tmux send-keys -t "$SESSION" -l $'\e[M#\x25'"$row_enc"
    sleep 0.05
done
sleep 1

# 6. Capture after rapid clicks
after_rapid=$(tmux capture-pane -t "$SESSION" -p)

echo "--- After rapid clicks ---"
check "CCMUX title survives rapid clicks" "CCMUX" "$after_rapid"
check "Session header survives rapid clicks" "Session:" "$after_rapid"
check "Repo content survives rapid clicks" "my-project" "$after_rapid"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
