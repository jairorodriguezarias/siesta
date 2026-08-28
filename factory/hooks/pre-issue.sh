#!/bin/bash
# pre-issue.sh — Runs before executing an issue
# Loads KB context for the issue
# Usage: ./pre-issue.sh <project_dir> <issue_number>
#
# Output (stdout): JSON with KB context to feed to the worker
# Output (stderr): Status messages

set -e

PROJECT_DIR="${1:-.}"
ISSUE_NUM="${2:-0}"

KB_FILE="$PROJECT_DIR/kb/graph.json"
KB_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/kb-manager.sh"

echo "[$(date +%H:%M:%S)] pre-issue: Loading KB context for issue #$ISSUE_NUM" >&2

# Query KB summaries (progressive disclosure — Level 1)
SUMMARIES=$("$KB_SCRIPT" query "$KB_FILE" --summary-only 2>/dev/null || echo "[]")

# Get relevant decisions (Level 1)
DECISIONS=$("$KB_SCRIPT" query "$KB_FILE" --type decision --summary-only 2>/dev/null || echo "[]")

# Get relevant learnings (Level 1)
LEARNINGS=$("$KB_SCRIPT" query "$KB_FILE" --type learning --summary-only 2>/dev/null || echo "[]")

# Get blockers (to avoid repeating mistakes)
BLOCKERS=$("$KB_SCRIPT" query "$KB_FILE" --type blocker --summary-only 2>/dev/null || echo "[]")

# Output JSON to stdout for the pipeline to consume
jq -n \
  --argjson summaries "$SUMMARIES" \
  --argjson decisions "$DECISIONS" \
  --argjson learnings "$LEARNINGS" \
  --argjson blockers "$BLOCKERS" \
  '{
    issue: $ISSUE_NUM,
    kb_summaries: $summaries,
    decisions: $decisions,
    learnings: $learnings,
    blockers: $blockers
  }' --arg ISSUE_NUM "$ISSUE_NUM" \
  '{issue: $ISSUE_NUM, kb_summaries: $summaries, decisions: $decisions, learnings: $learnings, blockers: $blockers}'

echo "[$(date +%H:%M:%S)] pre-issue: KB context loaded ($(echo "$SUMMARIES" | jq length) nodes)" >&2