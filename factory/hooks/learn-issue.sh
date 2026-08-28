#!/bin/bash
# learn-issue.sh — Micro-learning after each issue execution
# Qwen 2.5 analyzes what happened during this issue and learns from it
# Usage: ./learn-issue.sh <project_dir> <issue_number>
#
# Runs after post-issue.sh in the execute loop

set -e

PROJECT_DIR="${1:-.}"
ISSUE_NUM="${2:-0}"

FACTORY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$FACTORY_DIR/.agents/skills"
FACTORY_SKILLS_DIR="$FACTORY_DIR/skills"
KB_SCRIPT="$FACTORY_DIR/scripts/kb-manager.sh"
CONFIG_FILE="$FACTORY_DIR/config/models.json"
GLOBAL_KB="$FACTORY_DIR/kb/global-graph.json"
PROJECT_KB="$PROJECT_DIR/kb/graph.json"

WORKER_MODEL=$(jq -r '.worker.model' "$CONFIG_FILE")
WORKER_PROVIDER=$(jq -r '.worker.provider' "$CONFIG_FILE")

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✅${NC} $1" >&2; }
log_learn() { echo -e "${CYAN}[$(date +%H:%M:%S)] 🧠${NC} $1" >&2; }

# ─── Gather issue context ───
log_learn "Learning from issue #$ISSUE_NUM..."

ISSUE_OUTPUT=""
CONSULT_OUTPUT=""
PROXY_OUTPUT=""
RETRY_OUTPUT=""
HAD_CONSULT=false
HAD_PROXY=false
HAD_RETRY=false
HAD_BLOCKER=false

# Issue execution output
if [ -f "$PROJECT_DIR/issue_${ISSUE_NUM}_output.txt" ]; then
  ISSUE_OUTPUT=$(cat "$PROJECT_DIR/issue_${ISSUE_NUM}_output.txt")
fi

# Consultation?
if [ -f "$PROJECT_DIR/consult_${ISSUE_NUM}_output.txt" ]; then
  CONSULT_OUTPUT=$(cat "$PROJECT_DIR/consult_${ISSUE_NUM}_output.txt")
  HAD_CONSULT=true
fi

# Proxy decision?
if [ -f "$PROJECT_DIR/proxy_${ISSUE_NUM}_output.txt" ]; then
  PROXY_OUTPUT=$(cat "$PROJECT_DIR/proxy_${ISSUE_NUM}_output.txt")
  HAD_PROXY=true
fi

# Retry?
if [ -f "$PROJECT_DIR/issue_${ISSUE_NUM}_retry_output.txt" ]; then
  RETRY_OUTPUT=$(cat "$PROJECT_DIR/issue_${ISSUE_NUM}_retry_output.txt")
  HAD_RETRY=true
fi

# Blocker? Check KB for blocker on this issue
BLOCKER_CHECK=$("$KB_SCRIPT" query "$PROJECT_KB" --type blocker 2>/dev/null | jq -c --arg issue "Issue #$ISSUE_NUM" '[.[] | select(.summary | contains($issue))]' 2>/dev/null || echo "[]")
if [ "$(echo "$BLOCKER_CHECK" | jq 'length' 2>/dev/null)" -gt 0 ]; then
  HAD_BLOCKER=true
fi

# Issue text
ISSUE_TEXT=$(awk "/^## Issue #$ISSUE_NUM/{flag=1; next} /^## Issue #/{flag=0} flag" "$PROJECT_DIR/issues.md" 2>/dev/null | head -30)

# Global KB context
GLOBAL_SUMMARIES=$("$KB_SCRIPT" query "$GLOBAL_KB" --summary-only 2>/dev/null || echo "[]")

# Current factory skills
FACTORY_SKILLS=$(ls "$FACTORY_SKILLS_DIR" 2>/dev/null | tr '\n' ', ')

# ─── Qwen analyzes and learns ───
LEARN_PROMPT="You are the factory-learner. Follow the factory-learner skill.
Analyze what happened during issue #$ISSUE_NUM and learn from it. Be VERY granular and specific.

ISSUE #$ISSUE_NUM:
$ISSUE_TEXT

WHAT HAPPENED:
$(if $HAD_CONSULT; then echo "- Worker got STUCK and consulted GLM-5.2"; fi)
$(if $HAD_PROXY; then echo "- Worker requested PROXY approval"; fi)
$(if $HAD_RETRY; then echo "- Worker RETRIED (failed first attempt)"; fi)
$(if $HAD_BLOCKER; then echo "- Issue was BLOCKED"; fi)
$(if ! $HAD_CONSULT && ! $HAD_PROXY && ! $HAD_RETRY && ! $HAD_BLOCKER; then echo "- Issue executed cleanly (no issues)"; fi)

ISSUE OUTPUT (first 100 lines):
$(echo "$ISSUE_OUTPUT" | head -100)

$(if $HAD_CONSULT; then echo "CONSULTATION (worker asked GLM):"; echo "$CONSULT_OUTPUT" | head -50; echo "---"; fi)
$(if $HAD_PROXY; then echo "PROXY DECISION:"; echo "$PROXY_OUTPUT" | head -30; echo "---"; fi)
$(if $HAD_RETRY; then echo "RETRY OUTPUT (second attempt):"; echo "$RETRY_OUTPUT" | head -50; echo "---"; fi)

GLOBAL KB (learnings from ALL previous issues across ALL projects):
$GLOBAL_SUMMARIES

CURRENT FACTORY SKILLS (can improve these):
$FACTORY_SKILLS

Analyze with these specific questions:
1. Did the worker get stuck? WHY specifically? What was missing in the skill that could have prevented this?
2. If consulted, what was the question? Could the issue-executor skill cover this topic so future issues don't need to consult?
3. If proxy rejected, what was wrong with the worker's approach? What Red Flag should be added to prevent this?
4. If retried, what was the first attempt's mistake?
5. What decision was made? Is it a pattern that could repeat?
6. What went WELL that should be preserved as a best practice?
7. Is there a new pattern that no skill covers? (Only if truly novel AND likely to repeat)

Be EXTREMELY specific. Instead of 'improve testing', say 'add test for empty input in function X'.
Instead of 'worker made mistake', say 'worker tried approach X but should have used Y because Z'.

Output EXACTLY in this format:

ISSUE_LEARNING #$ISSUE_NUM:
  Stuck: $HAD_CONSULT
  Consulted: $HAD_CONSULT
  Proxy rejection: $HAD_PROXY
  Retried: $HAD_RETRY
  Blocked: $HAD_BLOCKER

  What went wrong:
    - <specific issue, or 'nothing'>

  Root cause:
    - <why it happened, or 'n/a'>

  What the skill should cover:
    - <specific guidance that was missing, or 'nothing'>

  What to do differently next time:
    - <actionable change, or 'nothing'>

  What went well:
    - <specific thing that worked, or 'nothing'>

  Actions:
    SKILL_IMPROVEMENT: <skill-name> — <exactly what to add and where>
    SKILL_IMPROVEMENT: <skill-name> — <what to add> (if more than one)
    NEW_SKILL: <name> — <what it covers> (only if truly novel)
    LEARNING: <summary> — <detail to log to global KB>
    LEARNING: <summary> — <detail> (if more than one)
    NO_ACTION: nothing to learn (rare)

  If improving a skill, also output the updated content block:
  SKILL_UPDATE_START: <skill-name>
  <full updated SKILL.md content>
  SKILL_UPDATE_END"

LEARN_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
  --skill "$FACTORY_SKILLS_DIR/factory-learner/" \
  --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
  --append-system-prompt "$LEARN_PROMPT" \
  "Learn from issue #$ISSUE_NUM" 2>&1)

echo "$LEARN_OUTPUT" > "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt"

# ─── Parse and act on learnings ───

# Log learnings to global KB
LEARNING_COUNT=0
while IFS= read -r line; do
  if [[ "$line" =~ LEARNING:[[:space:]]*(.+)[[:space:]]—[[:space:]]*(.+) ]]; then
    SUMMARY="${BASH_REMATCH[1]}"
    DETAIL="${BASH_REMATCH[2]}"
    "$KB_SCRIPT" append-node "$GLOBAL_KB" "learning" "$SUMMARY" "$DETAIL" >/dev/null 2>&1
    log_learn "Logged learning: $SUMMARY"
    LEARNING_COUNT=$((LEARNING_COUNT + 1))
  fi
done < "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt"

# Log skill improvements to global KB
IMPROVEMENT_COUNT=0
while IFS= read -r line; do
  if [[ "$line" =~ SKILL_IMPROVEMENT:[[:space:]]*(.+)[[:space:]]—[[:space:]]*(.+) ]]; then
    SKILL_NAME="${BASH_REMATCH[1]}"
    IMPROVEMENT="${BASH_REMATCH[2]}"
    "$KB_SCRIPT" append-node "$GLOBAL_KB" "decision" \
      "Skill improvement: $SKILL_NAME (issue #$ISSUE_NUM)" \
      "$IMPROVEMENT" >/dev/null 2>&1
    log_learn "Skill improvement: $SKILL_NAME — $IMPROVEMENT"
    IMPROVEMENT_COUNT=$((IMPROVEMENT_COUNT + 1))
  fi
done < "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt"

# Log new skill proposals
NEW_SKILL_COUNT=0
while IFS= read -r line; do
  if [[ "$line" =~ NEW_SKILL:[[:space:]]*(.+)[[:space:]]—[[:space:]]*(.+) ]]; then
    SKILL_NAME="${BASH_REMATCH[1]}"
    DESCRIPTION="${BASH_REMATCH[2]}"
    "$KB_SCRIPT" append-node "$GLOBAL_KB" "decision" \
      "New skill proposed: $SKILL_NAME (issue #$ISSUE_NUM)" \
      "$DESCRIPTION" >/dev/null 2>&1
    log_learn "New skill proposed: $SKILL_NAME"
    NEW_SKILL_COUNT=$((NEW_SKILL_COUNT + 1))
  fi
done < "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt"

# ─── Apply skill updates ───
if grep -q "SKILL_UPDATE_START:" "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt" 2>/dev/null; then
  log_learn "Applying skill updates..."
  python3 - "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt" "$FACTORY_SKILLS_DIR" << 'PYEOF'
import sys
import os
import re

output_file = sys.argv[1]
factory_skills_dir = sys.argv[2]

with open(output_file, 'r') as f:
    content = f.read()

pattern = r'SKILL_UPDATE_START:\s*(\S+)\n(.*?)SKILL_UPDATE_END'
matches = re.findall(pattern, content, re.DOTALL)

for skill_name, skill_content in matches:
    skill_content = skill_content.strip()
    skill_path = os.path.join(factory_skills_dir, skill_name, "SKILL.md")
    if os.path.exists(skill_path):
        with open(skill_path, 'w') as f:
            f.write(skill_content)
        print(f"  ✓ Updated: {skill_name}", file=sys.stderr)
    else:
        new_dir = os.path.join(factory_skills_dir, skill_name)
        os.makedirs(new_dir, exist_ok=True)
        new_path = os.path.join(new_dir, "SKILL.md")
        with open(new_path, 'w') as f:
            f.write(skill_content)
        print(f"  ✓ Created: {skill_name}", file=sys.stderr)
PYEOF
fi

# ─── Report ───
GLOBAL_FINAL_COUNT=$("$KB_SCRIPT" query "$GLOBAL_KB" --summary-only 2>/dev/null | jq 'length' 2>/dev/null || echo 0)

log_success "Issue #$ISSUE_NUM learning complete:"
echo "  Learnings logged:     $LEARNING_COUNT" >&2
echo "  Skill improvements:   $IMPROVEMENT_COUNT" >&2
echo "  New skills proposed:  $NEW_SKILL_COUNT" >&2
echo "  Global KB nodes:      $GLOBAL_FINAL_COUNT" >&2

# Output the learning report for the pipeline
grep -A 30 "ISSUE_LEARNING" "$PROJECT_DIR/learning_issue_${ISSUE_NUM}.txt" 2>/dev/null | head -25