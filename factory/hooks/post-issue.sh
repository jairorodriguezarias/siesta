#!/bin/bash
# post-issue.sh — Runs after executing an issue
# Logs the decision to KB and creates git commit
# Usage: ./post-issue.sh <project_dir> <issue_number> <output_file>
#
# Output (stdout): KB node ID
# Output (stderr): Status messages

set -e

PROJECT_DIR="${1:-.}"
ISSUE_NUM="${2:-0}"
OUTPUT_FILE="${3:-/dev/null}"

KB_FILE="$PROJECT_DIR/kb/graph.json"
KB_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/kb-manager.sh"

echo "[$(date +%H:%M:%S)] post-issue: Logging issue #$ISSUE_NUM to KB" >&2

# Read the issue output (truncate to reasonable size for KB)
ISSUE_OUTPUT=""
if [ -f "$OUTPUT_FILE" ]; then
  ISSUE_OUTPUT=$(head -200 "$OUTPUT_FILE")
fi

# Log decision to KB
NODE_ID=$("$KB_SCRIPT" append-node "$KB_FILE" "decision" \
  "Issue #$ISSUE_NUM completed" \
  "$ISSUE_OUTPUT")

# Git commit
cd "$PROJECT_DIR"
git add -A
git commit -m "🔧 Issue #$ISSUE_NUM: implemented" >/dev/null 2>&1

echo "[$(date +%H:%M:%S)] post-issue: KB node $NODE_ID created, git committed" >&2

# Output node ID to stdout
echo "$NODE_ID"