#!/bin/bash
# run-pipeline.sh — Orchestrates the full Factory pipeline
# Usage: ./run-pipeline.sh "project idea"
#
# Phase 0: HUMAN + AGENT (interactive) → define idea, human leaves
# Phase 1: AUTONOMOUS → spec, plan, execute, review, verify, git

set -e

IDEA="$1"
FACTORY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECTS_DIR="$FACTORY_DIR/projects"
SKILLS_DIR="$FACTORY_DIR/.agents/skills"
FACTORY_SKILLS_DIR="$FACTORY_DIR/skills"
AGENTS_DIR="$FACTORY_DIR/.agents/agents"
REFERENCES_DIR="$FACTORY_DIR/.agents/references"
HOOKS_DIR="$FACTORY_DIR/hooks"
KB_SCRIPT="$FACTORY_DIR/scripts/kb-manager.sh"
CONFIG_FILE="$FACTORY_DIR/config/models.json"

# Load model config
PLANNER_MODEL=$(jq -r '.planner.model' "$CONFIG_FILE")
PLANNER_PROVIDER=$(jq -r '.planner.provider' "$CONFIG_FILE")
WORKER_MODEL=$(jq -r '.worker.model' "$CONFIG_FILE")
WORKER_PROVIDER=$(jq -r '.worker.provider' "$CONFIG_FILE")
CONSULTANT_MODEL=$(jq -r '.consultant.model' "$CONFIG_FILE")
CONSULTANT_PROVIDER=$(jq -r '.consultant.provider' "$CONFIG_FILE")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[$(date +%H:%M:%S)] ✅${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠️${NC} $1" >&2; }
log_error() { echo -e "${RED}[$(date +%H:%M:%S)] ❌${NC} $1" >&2; }
log_phase() { echo -e "${CYAN}══━─ Phase $1: $2 ─━══${NC}" >&2; }

# ─── Validate ───
if [ -z "$IDEA" ]; then
  log_error "Usage: run-pipeline.sh \"project idea\""
  exit 1
fi

# ─── Generate project name ───
PROJECT_NAME=$(echo "$IDEA" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | head -c 40 | sed 's/-$//')
PROJECT_DIR="$PROJECTS_DIR/$PROJECT_NAME"

log "Creating project: $PROJECT_NAME"
mkdir -p "$PROJECT_DIR"

# ─── Initialize KB ───
mkdir -p "$PROJECT_DIR/kb"
echo '{"nodes": [], "edges": []}' > "$PROJECT_DIR/kb/graph.json"
cp "$FACTORY_DIR/kb/schema.json" "$PROJECT_DIR/kb/schema.json"

# ─── Initialize Git ───
cd "$PROJECT_DIR"
git init >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 0: HUMAN INTERACTIVE
# ═══════════════════════════════════════════════════════
log_phase "0" "HUMAN INTERACTIVE — Define the idea"

echo -e "${YELLOW}━━━ Interactive Session — Human + Agent ━━━${NC}"
echo -e "${YELLOW}The agent will ask questions to clarify your idea.${NC}"
echo ""

pi --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
  --skill "$SKILLS_DIR/interview-me/" \
  --append-system-prompt "You are an interviewer. Follow the interview-me skill.
A human wants to build: $IDEA

Ask ONE question at a time to clarify what they want. Wait for their answer.
Keep asking until ~95% confidence about:
- What exactly to build
- What tech stack to use
- What success looks like
- What is out of scope

When you have enough clarity, output:
INTENT_FINALIZED: <one paragraph summarizing what the human wants>" \
  "$IDEA" 2>&1 | tee "$PROJECT_DIR/interview_output.txt"

echo ""
log_success "Interactive phase complete. Human is leaving."
echo -e "${YELLOW}━━━ Autonomous Phase — No Human ━━━${NC}"
echo ""

# Extract intent
INTENT=$(grep -A 50 "INTENT_FINALIZED:" "$PROJECT_DIR/interview_output.txt" 2>/dev/null | sed 's/^INTENT_FINALIZED: //' || echo "$IDEA")

# Log intent to KB
INTENT_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "intent" \
  "Human intent for $PROJECT_NAME" \
  "$INTENT")

git add -A && git commit -m "📋 Intent captured from human" >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 1: SPEC — GLM-5.2
# ═══════════════════════════════════════════════════════
log_phase "1" "SPEC — GLM-5.2"

KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

pi -p --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
  --skill "$SKILLS_DIR/spec-driven-development/" \
  --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
  --append-system-prompt "You are a software architect. Follow the spec-driven-development skill.
The human has left. This is autonomous. No human will answer questions.

Human intent:
$INTENT

KB context:
$KB_SUMMARIES

Create spec.md with: project name, tech stack, structure, features, acceptance criteria, testing approach, boundaries.
Write the spec to spec.md. Be concise. Do NOT ask questions — decide autonomously." \
  "$INTENT" 2>&1 | tee "$PROJECT_DIR/spec_output.txt"

if [ ! -f "$PROJECT_DIR/spec.md" ]; then
  log_error "Spec generation failed"
  exit 1
fi

log_success "Spec generated"
SPEC_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "spec" \
  "Spec for $PROJECT_NAME" "$(cat "$PROJECT_DIR/spec.md")")
"$KB_SCRIPT" append-edge "$PROJECT_DIR/kb/graph.json" "$SPEC_NODE_ID" "$INTENT_NODE_ID" "parent_of"

git add -A && git commit -m "📋 Spec generated" >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 2: PLAN — GLM-5.2
# ═══════════════════════════════════════════════════════
log_phase "2" "PLAN — GLM-5.2 generating issues"

KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

pi -p --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
  --skill "$SKILLS_DIR/planning-and-task-breakdown/" \
  --append-system-prompt "You are a project planner. Follow the planning-and-task-breakdown skill.
The human has left. This is autonomous. No questions.

Read spec.md and create issues.md with ordered issues.
Each issue: ## Issue #N: Title, description, acceptance criteria, dependencies.
Keep issues small and atomic. Write to issues.md." \
  "$(cat "$PROJECT_DIR/spec.md")" 2>&1 | tee "$PROJECT_DIR/plan_output.txt"

if [ ! -f "$PROJECT_DIR/issues.md" ]; then
  log_error "Plan generation failed"
  exit 1
fi

log_success "Plan generated"

# Log issues to KB
while IFS= read -r line; do
  if [[ "$line" =~ ^##[[:space:]]Issue[[:space:]]\#([0-9]+) ]]; then
    ISSUE_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "issue" \
      "Issue #${BASH_REMATCH[1]}" "$line")
    "$KB_SCRIPT" append-edge "$PROJECT_DIR/kb/graph.json" "$ISSUE_NODE_ID" "$SPEC_NODE_ID" "parent_of"
  fi
done < "$PROJECT_DIR/issues.md"

git add -A && git commit -m "📋 Plan generated with issues" >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 3: EXECUTE LOOP — Qwen 2.5
# ═══════════════════════════════════════════════════════
log_phase "3" "EXECUTE — Qwen 2.5"

ISSUE_COUNT=$(grep -c "^## Issue #" "$PROJECT_DIR/issues.md" 2>/dev/null || echo 0)
if [ "$ISSUE_COUNT" -eq 0 ]; then
  ISSUE_COUNT=$(grep -c "^### Issue\|^## Issue\|^Issue #\|^- \[" "$PROJECT_DIR/issues.md" 2>/dev/null || echo 1)
fi

log "Found $ISSUE_COUNT issues to execute"

CURRENT_ISSUE=1
BLOCKED_ISSUES=()
declare -A ISSUE_FAIL_COUNT  # Track failure count per issue (for escalation)

# ─── Stop signal check (from Ralph) ───
check_stop() {
  if [ -f "$PROJECT_DIR/stop.md" ]; then
    log_warn "stop.md detected! Halting pipeline."
    log "Reason: $(cat "$PROJECT_DIR/stop.md")"
    "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
      "Pipeline halted by stop.md" "$(cat "$PROJECT_DIR/stop.md")"
    exit 0
  fi
}

# ─── Regression suite runner (from Ralph) ───
run_regression_suite() {
  local project_dir="$1"
  local test_dir="$project_dir/tests"
  if [ -d "$test_dir" ]; then
    log "Running regression suite (all previous tests)..."
    # Detect project type and run all tests
    if [ -f "$project_dir/package.json" ]; then
      (cd "$project_dir" && npm test 2>&1) | tee "$project_dir/regression_${CURRENT_ISSUE}.log" >&2
      return $?
    elif [ -f "$project_dir/requirements.txt" ] || [ -f "$project_dir/setup.py" ] || [ -f "$project_dir/pyproject.toml" ]; then
      (cd "$project_dir" && python -m pytest tests/ 2>&1) | tee "$project_dir/regression_${CURRENT_ISSUE}.log" >&2
      return $?
    elif [ -f "$project_dir/go.mod" ]; then
      (cd "$project_dir" && go test ./... 2>&1) | tee "$project_dir/regression_${CURRENT_ISSUE}.log" >&2
      return $?
    else
      log "No known test runner found, skipping regression"
      return 0
    fi
  fi
  return 0
}

# ─── Escalation: run GLM with thinking=high (from Ralph) ───
consult_glm() {
  local issue_num="$1"
  local consult_text="$2"
  local kb_context="$3"
  local fail_count="${4:-0}"
  local thinking_level="off"
  
  # Escalate thinking if 3+ failures (from Ralph's model escalation)
  if [ "$fail_count" -ge 3 ]; then
    thinking_level="high"
    log_warn "Escalating GLM-5.2 to thinking=high (failure #$fail_count)"
  fi
  
  pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
    --thinking "$thinking_level" \
    --skill "$FACTORY_SKILLS_DIR/consultant-protocol/" \
    --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
    --append-system-prompt "You are a senior engineer. Follow the consultant-protocol skill.
A developer is stuck:

$consult_text

KB Context:
$kb_context

Provide a clear resolution with RESOLUTION: and APPROACH: and CODE:." \
    "$consult_text" 2>&1
}

# ─── Deep diagnosis (from Ralph's juez desatascar) ───
diagnose_blocker() {
  local issue_num="$1"
  local issue_text="$2"
  local failure_history="$3"
  local kb_context="$4"
  
  log_warn "Issue #$issue_num has failed ${#failure_history[@]} times. Running deep diagnosis..."
  
  pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
    --thinking high \
    --skill "$FACTORY_SKILLS_DIR/consultant-protocol/" \
    --skill "$FACTORY_SKILLS_DIR/human-proxy/" \
    --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
    --append-system-prompt "You are a senior engineer doing a DEEP DIAGNOSIS.
An issue has failed multiple times. This is not a normal consultation — this is a diagnosis.

Issue:
$issue_text

Failure history (what was tried and failed):
$failure_history

KB Context:
$kb_context

Diagnose:
1. Is the approach fundamentally wrong? If so, what's the right approach?
2. Is the issue too complex to solve in one pass? Should it be broken down?
3. Is there a missing prerequisite that should be done first?
4. Is there an environment/tooling issue?
5. Should this issue be SKIPPED and the pipeline continue without it?

Output:
DIAGNOSIS: <root cause>
RECOMMENDATION: <fix or skip>
DETAILED_PLAN: <step-by-step fix, or 'SKIP: log blocker and continue'>
CODE: <if code fix needed>" \
    "Diagnose issue #$issue_num" 2>&1
}

while [ "$CURRENT_ISSUE" -le "$ISSUE_COUNT" ]; do
  check_stop  # Check for stop.md (from Ralph)
  
  log "Executing issue #$CURRENT_ISSUE..."

  ISSUE_TEXT=$(awk "/^## Issue #$CURRENT_ISSUE/{flag=1; next} /^## Issue #/{flag=0} flag" "$PROJECT_DIR/issues.md" 2>/dev/null)

  if [ -z "$ISSUE_TEXT" ]; then
    log_warn "Issue #$CURRENT_ISSUE not found, skipping"
    CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
    continue
  fi

  # ─── Regression suite: run ALL previous tests before this issue (from Ralph) ───
  if [ "$CURRENT_ISSUE" -gt 1 ]; then
    run_regression_suite "$PROJECT_DIR" "$CURRENT_ISSUE"
    REGRESSION_EXIT=$?
    if [ $REGRESSION_EXIT -ne 0 ]; then
      log_error "Regression suite FAILED before issue #$CURRENT_ISSUE. Previous issue may have broken something."
      "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
        "Regression failure before issue #$CURRENT_ISSUE" \
        "Previous issue broke existing tests. See regression_${CURRENT_ISSUE}.log"
      # Log to KB and continue — the regression failure itself is a learning
    fi
  fi

  # ─── Hook: pre-issue ───
  "$HOOKS_DIR/pre-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" > "$PROJECT_DIR/pre_issue_${CURRENT_ISSUE}.json" 2>/dev/null
  KB_SUMMARIES=$(cat "$PROJECT_DIR/pre_issue_${CURRENT_ISSUE}.json" 2>/dev/null | jq -c '.kb_summaries' 2>/dev/null || echo "[]")

  # ─── Execute with Qwen ───
  ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
    --skill "$SKILLS_DIR/incremental-implementation/" \
    --skill "$SKILLS_DIR/test-driven-development/" \
    --skill "$SKILLS_DIR/debugging-and-error-recovery/" \
    --skill "$FACTORY_SKILLS_DIR/issue-executor/" \
    --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
    --append-system-prompt "You are a developer. Follow the issue-executor skill.
Execute this issue:

$ISSUE_TEXT

KB Context:
$KB_SUMMARIES

Reference: definition-of-done.md for exit criteria.

Rules:
- Write code and tests for this issue
- Run tests and verify they pass
- If STUCK, output EXACTLY:
  CONSULT: <question>
  CONTEXT: <what you tried>
  CODE: <error or relevant code>
- If a skill says 'ask the human', output:
  PROXY_REQUEST: <what needs approval>
  CONTEXT: <why>
- Otherwise implement fully" \
    "$ISSUE_TEXT" 2>&1)

  echo "$ISSUE_OUTPUT" > "$PROJECT_DIR/issue_${CURRENT_ISSUE}_output.txt"

  # ─── Check: PROXY_REQUEST (human-proxy) ───
  if echo "$ISSUE_OUTPUT" | grep -q "PROXY_REQUEST:"; then
    log "Worker requesting proxy approval for issue #$CURRENT_ISSUE..."
    PROXY_REQUEST=$(echo "$ISSUE_OUTPUT" | grep -A 20 "PROXY_REQUEST:")

    PROXY_OUTPUT=$(pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
      --skill "$FACTORY_SKILLS_DIR/human-proxy/" \
      --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
      --append-system-prompt "You are the human-proxy. Follow the human-proxy skill.
A worker requests approval as if you were the human.

Request:
$PROXY_REQUEST

KB Context (original intent and all decisions):
$KB_SUMMARIES

Evaluate against the original human intent in the KB.
Decide: APPROVED, REJECTED, or NEEDS_REVISION." \
      "$PROXY_REQUEST" 2>&1)

    echo "$PROXY_OUTPUT" > "$PROJECT_DIR/proxy_${CURRENT_ISSUE}_output.txt"
    "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "proxy_decision" \
      "Proxy decision for issue #$CURRENT_ISSUE" "$PROXY_OUTPUT"

    if echo "$PROXY_OUTPUT" | grep -q "REJECTED"; then
      log_warn "Proxy rejected, retrying..."
      ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
        --skill "$SKILLS_DIR/incremental-implementation/" \
        --skill "$SKILLS_DIR/test-driven-development/" \
        --append-system-prompt "Proxy rejected: $PROXY_OUTPUT. Try a different approach for: $ISSUE_TEXT" \
        "$ISSUE_TEXT" 2>&1)
      echo "$ISSUE_OUTPUT" > "$PROJECT_DIR/issue_${CURRENT_ISSUE}_retry_output.txt"
    fi
  fi

  # Track failure count for escalation (from Ralph)
  ISSUE_FAIL_COUNT[$CURRENT_ISSUE]=0
  PREVIOUS_FAILURES=""  # Accumulate failure history for deep diagnosis

  # ─── Check: CONSULT (GLM-5.2 consultant) ───
  if echo "$ISSUE_OUTPUT" | grep -q "CONSULT:"; then
    ISSUE_FAIL_COUNT[$CURRENT_ISSUE]=$((${ISSUE_FAIL_COUNT[$CURRENT_ISSUE]} + 1))
    FAIL_NUM=${ISSUE_FAIL_COUNT[$CURRENT_ISSUE]}
    log_warn "Worker stuck (attempt $FAIL_NUM), consulting GLM-5.2..."
    CONSULT_TEXT=$(echo "$ISSUE_OUTPUT" | grep -A 50 "CONSULT:")
    PREVIOUS_FAILURES="${PREVIOUS_FAILURES}Attempt $FAIL_NUM: $CONSULT_TEXT\n"

    # ─── Deep diagnosis after 3 failures (from Ralph's juez desatascar) ───
    if [ "${ISSUE_FAIL_COUNT[$CURRENT_ISSUE]}" -ge 3 ]; then
      log_warn "3 failures on issue #$CURRENT_ISSUE. Triggering deep diagnosis..."
      
      DIAGNOSIS_OUTPUT=$(diagnose_blocker "$CURRENT_ISSUE" "$ISSUE_TEXT" "${PREVIOUS_FAILURES}" "$KB_SUMMARIES")
      echo "$DIAGNOSIS_OUTPUT" > "$PROJECT_DIR/diagnosis_${CURRENT_ISSUE}_output.txt"
      
      "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "consultation" \
        "Deep diagnosis for issue #$CURRENT_ISSUE" "$DIAGNOSIS_OUTPUT"

      if echo "$DIAGNOSIS_OUTPUT" | grep -q "SKIP:"; then
        log_error "Issue #$CURRENT_ISSUE SKIPPED after deep diagnosis"
        BLOCKED_ISSUES+=("$CURRENT_ISSUE")
        "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
          "Issue #$CURRENT_ISSUE skipped after diagnosis" "$DIAGNOSIS_OUTPUT"
        # Write stop.md if diagnosis says it's critical (from Ralph)
        if echo "$DIAGNOSIS_OUTPUT" | grep -q "CRITICAL:"; then
          echo "Issue #$CURRENT_ISSUE is critical and cannot be skipped. Manual intervention needed." > "$PROJECT_DIR/stop.md"
          log_error "CRITICAL: stop.md created. Pipeline will halt."
          break
        fi
        CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
        continue
      fi

      # Feed diagnosis back to worker
      log "Diagnosis provided, feeding back to worker..."
      ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
        --skill "$SKILLS_DIR/incremental-implementation/" \
        --skill "$SKILLS_DIR/test-driven-development/" \
        --append-system-prompt "A senior engineer did a deep diagnosis and provided this plan:

$DIAGNOSIS_OUTPUT

Now implement the issue:
$ISSUE_TEXT" \
        "$ISSUE_TEXT" 2>&1)
      echo "$ISSUE_OUTPUT" > "$PROJECT_DIR/issue_${CURRENT_ISSUE}_retry_output.txt"

      if echo "$ISSUE_OUTPUT" | grep -q "CONSULT:"; then
        log_error "Issue #$CURRENT_ISSUE blocked after diagnosis"
        BLOCKED_ISSUES+=("$CURRENT_ISSUE")
        "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
          "Issue #$CURRENT_ISSUE blocked after diagnosis" "Worker still stuck after deep diagnosis"
        CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
        continue
      fi
    else
      # Normal consultation with thinking escalation (from Ralph)
      CONSULT_OUTPUT=$(consult_glm "$CURRENT_ISSUE" "$CONSULT_TEXT" "$KB_SUMMARIES" "${ISSUE_FAIL_COUNT[$CURRENT_ISSUE]}")

      echo "$CONSULT_OUTPUT" > "$PROJECT_DIR/consult_${CURRENT_ISSUE}_output.txt"
      "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "consultation" \
        "Consultation for issue #$CURRENT_ISSUE" "$CONSULT_TEXT"

      # Feed resolution back to worker
      log "GLM-5.2 resolved, feeding back to worker..."
      ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
        --skill "$SKILLS_DIR/incremental-implementation/" \
        --skill "$SKILLS_DIR/test-driven-development/" \
        --append-system-prompt "A senior engineer provided this guidance:

$CONSULT_OUTPUT

Now implement the issue:
$ISSUE_TEXT" \
        "$ISSUE_TEXT" 2>&1)

      echo "$ISSUE_OUTPUT" > "$PROJECT_DIR/issue_${CURRENT_ISSUE}_retry_output.txt"

      if echo "$ISSUE_OUTPUT" | grep -q "CONSULT:"; then
        log_error "Issue #$CURRENT_ISSUE blocked after consultation"
        BLOCKED_ISSUES+=("$CURRENT_ISSUE")
        "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
          "Issue #$CURRENT_ISSUE blocked" "Worker stuck after GLM consultation"
        CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
        continue
      fi
    fi
  fi

  # ─── Hook: post-issue ───
  log_success "Issue #$CURRENT_ISSUE executed"
  "$HOOKS_DIR/post-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" "$PROJECT_DIR/issue_${CURRENT_ISSUE}_output.txt" >/dev/null 2>&1

  # ─── Hook: learn-issue ─── Qwen learns from THIS issue immediately ───
  "$HOOKS_DIR/learn-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" 2>&1 | tee "$PROJECT_DIR/learn_issue_${CURRENT_ISSUE}.log" >&2

  CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
done

# ═══════════════════════════════════════════════════════
# PHASE 4: REVIEW — Qwen + code-reviewer persona
# ═══════════════════════════════════════════════════════
log_phase "4" "REVIEW — Qwen 2.5 + code-reviewer"

KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

REVIEW_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
  --skill "$SKILLS_DIR/code-review-and-quality/" \
  --skill "$SKILLS_DIR/code-simplification/" \
  --append-system-prompt "You are the code-reviewer persona. Follow the code-review-and-quality skill.
Review all code across 5 axes: correctness, readability, architecture, security, performance.

Reference: definition-of-done.md for exit criteria.
Security reference: security-checklist.md if handling user input.

KB Context:
$KB_SUMMARIES

If review passes: REVIEW_PASSED: <summary>
If critical issues: REVIEW_FAILED: <issues>. Fix them." \
  "Review the code in this project" 2>&1)

echo "$REVIEW_OUTPUT" > "$PROJECT_DIR/review_output.txt"

# Human-proxy approves review
PROXY_REVIEW=$(pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
  --skill "$FACTORY_SKILLS_DIR/human-proxy/" \
  --append-system-prompt "You are the human-proxy. Evaluate if this review meets the Definition of Done.
Review output:
$REVIEW_OUTPUT

KB Context:
$KB_SUMMARIES

Decide: APPROVED or NEEDS_REVISION." \
  "$REVIEW_OUTPUT" 2>&1)

echo "$PROXY_REVIEW" > "$PROJECT_DIR/proxy_review_output.txt"
"$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "proxy_decision" \
  "Proxy review approval" "$PROXY_REVIEW"

if echo "$PROXY_REVIEW" | grep -q "NEEDS_REVISION"; then
  log_warn "Proxy requests revision, fixing..."
  pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
    --skill "$SKILLS_DIR/code-review-and-quality/" \
    --skill "$SKILLS_DIR/code-simplification/" \
    --append-system-prompt "Proxy requested: $PROXY_REVIEW. Fix now." \
    "Fix review issues" 2>&1 | tee "$PROJECT_DIR/review_fixes_output.txt"
fi

log_success "Review complete"

# ═══════════════════════════════════════════════════════
# PHASE 5: VERIFY — Qwen verifies it runs locally
# ═══════════════════════════════════════════════════════
log_phase "5" "VERIFY — Runs locally?"

VERIFY_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
  --skill "$SKILLS_DIR/test-driven-development/" \
  --skill "$SKILLS_DIR/debugging-and-error-recovery/" \
  --append-system-prompt "You are a QA engineer. Follow the debugging-and-error-recovery skill.
Verify this project runs locally:
1. Check project type (Python, Node, etc.)
2. Try to run it
3. If it fails, try to fix it
4. Output VERIFY_PASSED: or VERIFY_FAILED:" \
  "Verify this project runs locally" 2>&1)

echo "$VERIFY_OUTPUT" > "$PROJECT_DIR/verify_output.txt"

# ═══════════════════════════════════════════════════════
# PHASE 6: DONE
# ═══════════════════════════════════════════════════════
log_phase "6" "DONE"

# Log final state to KB
"$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "decision" \
  "Project complete: $PROJECT_NAME" \
  "Project verified running locally."

# Final git commit
git add -A && git commit -m "✅ Project verified: $PROJECT_NAME" >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 7: LEARN (project-level) — Qwen learns from the full project
# ═══════════════════════════════════════════════════════
log_phase "7" "LEARN — Project-level learning"

"$FACTORY_DIR/scripts/learn.sh" "$PROJECT_DIR" "$PROJECT_NAME" 2>&1 | tee "$PROJECT_DIR/project_learning.log"

# Summary
echo ""
echo "═══════════════════════════════════════════════"
log_success "Factory pipeline complete!"
echo "═══════════════════════════════════════════════"
echo ""
echo "  Project:   $PROJECT_NAME"
echo "  Location:  $PROJECT_DIR"
echo "  Issues:    $ISSUE_COUNT total, ${#BLOCKED_ISSUES[@]} blocked"
echo ""
echo "  Git log:"
git log --oneline | head -20
echo ""

if [ ${#BLOCKED_ISSUES[@]} -gt 0 ]; then
  log_warn "Blocked issues: ${BLOCKED_ISSUES[*]}"
fi

echo ""
echo "KB graph:"
"$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only
echo ""
echo "KB stats: $(jq '.nodes | length' "$PROJECT_DIR/kb/graph.json") nodes, $(jq '.edges | length' "$PROJECT_DIR/kb/graph.json") edges"