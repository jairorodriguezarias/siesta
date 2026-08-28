#!/bin/bash
# learn.sh — Project-level learning (runs AFTER all issues are done)
# Qwen 2.5 reads all issue learnings from global KB, identifies cross-issue patterns
# Usage: ./learn.sh <project_dir> <project_name>
#
# This is Phase 7. Per-issue learning already happened via learn-issue.sh.
# This script does the PROJECT-LEVEL summary: cross-issue patterns, skill restructure.

set -e

PROJECT_DIR="${1:-.}"
PROJECT_NAME="${2:-unknown}"

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
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✅${NC} $1" >&2; }
log_learn() { echo -e "${CYAN}[$(date +%H:%M:%S)] 🧠${NC} $1" >&2; }

log "Phase 7: PROJECT-LEVEL LEARNING — Analyzing cross-issue patterns..."

# ─── Read all per-issue learnings from this project ───
ISSUE_LEARNINGS=""
for f in "$PROJECT_DIR"/learning_issue_*.txt; do
  if [ -f "$f" ]; then
    ISSUE_LEARNINGS="${ISSUE_LEARNINGS}$(cat "$f" | grep -A 30 "ISSUE_LEARNING")\n---\n"
  fi
done

# ─── Read global KB (includes per-issue learnings already logged) ───
GLOBAL_SUMMARIES=$("$KB_SCRIPT" query "$GLOBAL_KB" --summary-only 2>/dev/null || echo "[]")
GLOBAL_COUNT=$(echo "$GLOBAL_SUMMARIES" | jq 'length' 2>/dev/null || echo 0)

# ─── Read project KB ───
PROJECT_BLOCKERS=$("$KB_SCRIPT" query "$PROJECT_KB" --type blocker 2>/dev/null || echo "[]")
PROJECT_CONSULTATIONS=$("$KB_SCRIPT" query "$PROJECT_KB" --type consultation 2>/dev/null || echo "[]")
PROJECT_DECISIONS=$("$KB_SCRIPT" query "$PROJECT_KB" --type decision 2>/dev/null || echo "[]")

BLOCKER_COUNT=$(echo "$PROJECT_BLOCKERS" | jq 'length' 2>/dev/null || echo 0)
CONSULT_COUNT=$(echo "$PROJECT_CONSULTATIONS" | jq 'length' 2>/dev/null || echo 0)
DECISION_COUNT=$(echo "$PROJECT_DECISIONS" | jq 'length' 2>/dev/null || echo 0)

# ─── List current factory skills ───
FACTORY_SKILLS=$(ls "$FACTORY_SKILLS_DIR" 2>/dev/null | tr '\n' ', ')

log "Project: $PROJECT_NAME"
log "Blockers: $BLOCKER_COUNT, Consultations: $CONSULT_COUNT, Decisions: $DECISION_COUNT"
log "Global KB: $GLOBAL_COUNT nodes (includes per-issue learnings from this project)"

# ─── Qwen does cross-issue analysis ───
LEARN_PROMPT="You are the factory-learner. Follow the factory-learner skill (Level 2: Project-End Learning).

Per-issue learning already happened. Now do the PROJECT-LEVEL summary.

PROJECT: $PROJECT_NAME

ALL PER-ISSUE LEARNINGS (from this project):
$ISSUE_LEARNINGS

PROJECT KB:
Blockers ($BLOCKER_COUNT): $PROJECT_BLOCKERS
Consultations ($CONSULT_COUNT): $PROJECT_CONSULTATIONS
Decisions ($DECISION_COUNT): $PROJECT_DECISIONS

GLOBAL KB (all learnings including per-issue from this project):
$GLOBAL_SUMMARIES

CURRENT FACTORY SKILLS:
$FACTORY_SKILLS

Your job (project-level):
1. Identify CROSS-ISSUE patterns — things that appeared in multiple issues
2. Check if any factory skill should be RESTRUCTURED (not just appended to)
3. Were there related blockers across issues? Same root cause?
4. Were consultations about the same topic? Skill should cover that topic
5. What's the overall project learning? (one paragraph)
6. Should a new skill be created based on cross-issue patterns?

Output EXACTLY:

PROJECT_LEARNING:
  Project: $PROJECT_NAME
  Issues executed: N
  Blockers: $BLOCKER_COUNT
  Consultations: $CONSULT_COUNT
  Decisions: $DECISION_COUNT

  Cross-issue patterns:
    - <pattern that appeared in multiple issues, or 'none'>

  Skills to restructure:
    - <skill-name>: <what structural change is needed, or 'none'>

  New skills (from cross-issue patterns):
    - <name>: <what it covers, or 'none'>

  Overall project learning:
    <one paragraph summary of what this project taught the factory>

  Actions:
    LEARNING: <summary> — <detail to log to global KB>
    LEARNING: <summary> — <detail> (if more)
    SKILL_IMPROVEMENT: <skill> — <structural change> (if any)
    NEW_SKILL: <name> — <what> (if any)

  If restructuring a skill, output the full updated content:
  SKILL_UPDATE_START: <skill-name>
  <full updated SKILL.md>
  SKILL_UPDATE_END"

LEARN_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
  --skill "$FACTORY_SKILLS_DIR/factory-learner/" \
  --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
  --append-system-prompt "$LEARN_PROMPT" \
  "$PROJECT_NAME" 2>&1)

echo "$LEARN_OUTPUT" > "$PROJECT_DIR/project_learning_output.txt"

# ─── Parse and act ───
LEARNING_COUNT=0
while IFS= read -r line; do
  if [[ "$line" =~ LEARNING:[[:space:]]*(.+)[[:space:]]—[[:space:]]*(.+) ]]; then
    SUMMARY="${BASH_REMATCH[1]}"
    DETAIL="${BASH_REMATCH[2]}"
    "$KB_SCRIPT" append-node "$GLOBAL_KB" "learning" "$SUMMARY" "$DETAIL" >/dev/null 2>&1
    LEARNING_COUNT=$((LEARNING_COUNT + 1))
  fi
done < "$PROJECT_DIR/project_learning_output.txt"

# Apply skill updates
if grep -q "SKILL_UPDATE_START:" "$PROJECT_DIR/project_learning_output.txt" 2>/dev/null; then
  log_learn "Applying project-level skill updates..."
  python3 - "$PROJECT_DIR/project_learning_output.txt" "$FACTORY_SKILLS_DIR" << 'PYEOF'
import sys, os, re
with open(sys.argv[1], 'r') as f: content = f.read()
for skill_name, skill_content in re.findall(r'SKILL_UPDATE_START:\s*(\S+)\n(.*?)SKILL_UPDATE_END', content, re.DOTALL):
    skill_path = os.path.join(sys.argv[2], skill_name, "SKILL.md")
    if os.path.exists(skill_path):
        with open(skill_path, 'w') as f: f.write(skill_content.strip())
        print(f"  ✓ Restructured: {skill_name}", file=sys.stderr)
    else:
        os.makedirs(os.path.join(sys.argv[2], skill_name), exist_ok=True)
        with open(os.path.join(sys.argv[2], skill_name, "SKILL.md"), 'w') as f: f.write(skill_content.strip())
        print(f"  ✓ Created: {skill_name}", file=sys.stderr)
PYEOF
fi

GLOBAL_FINAL_COUNT=$("$KB_SCRIPT" query "$GLOBAL_KB" --summary-only 2>/dev/null | jq 'length' 2>/dev/null || echo 0)

log_success "Project-level learning complete!"
echo "  New learnings logged: $LEARNING_COUNT" >&2
echo "  Global KB: $GLOBAL_COUNT → $GLOBAL_FINAL_COUNT nodes" >&2
echo "" >&2

# Show report
grep -A 40 "PROJECT_LEARNING:" "$PROJECT_DIR/project_learning_output.txt" 2>/dev/null | head -35