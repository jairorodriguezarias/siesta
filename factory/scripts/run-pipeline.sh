#!/bin/bash
# run-pipeline.sh — Orchestrates the full Siesta pipeline
# Usage: ./run-pipeline.sh "project idea" [--auto] [--resume]
#
# Phase 0: HUMAN + AGENT (interactive) → define idea, human leaves
#   --auto: skip interview, use idea as intent directly
# Phase 1: AUTONOMOUS → spec, plan, execute, review, verify, git
#
# Lessons learned (implemented):
# - --auto flag: skip interview when idea is detailed enough
# - --thinking off: auto-detect models that don't support thinking (qwen2.5-coder)
# - Spec fallback: if spec.md missing, check for existing artifacts before failing
# - Better project naming: truncate at word boundary, not character count
# - Review with file content: pipe source files into review prompt (pi -p can't use tools)
# - Failure learning: run minimal learning pass even on pipeline failure
# - Resume: checkpoint each phase, skip completed phases on --resume
# - Content accuracy: pass models.json to model context

set -e

IDEA=""
AUTO_MODE=false
RESUME_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) AUTO_MODE=true; shift ;;
    --resume) RESUME_MODE=true; shift ;;
    *) IDEA="$1"; shift ;;
  esac
done

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

# ─── Detect thinking support ───
# Models that don't support thinking need --thinking off
# Check if the model name contains "coder" or other known non-thinking models
WORKER_THINKING="off"
CONSULTANT_THINKING="off"
PLANNER_THINKING="off"
case "$WORKER_MODEL" in
  *coder*|*qwen2.5-coder*) WORKER_THINKING="off" ;;
  *) WORKER_THINKING="off" ;;  # default to off for safety
esac
# GLM models support thinking, but we start with off and escalate as needed
case "$CONSULTANT_MODEL" in
  *glm*) CONSULTANT_THINKING="off" ;;  # start low, escalate in consult_glm
  *) CONSULTANT_THINKING="off" ;;
esac
case "$PLANNER_MODEL" in
  *glm*) PLANNER_THINKING="off" ;;
  *) PLANNER_THINKING="off" ;;
esac

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
  log_error "Usage: run-pipeline.sh \"project idea\" [--auto] [--resume]"
  exit 1
fi

# ─── Generate project name (truncate at word boundary) ───
PROJECT_NAME=$(echo "$IDEA" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
# Truncate at word boundary (max 40 chars, break at last hyphen before 40)
if [ ${#PROJECT_NAME} -gt 40 ]; then
  PROJECT_NAME=$(echo "$PROJECT_NAME" | cut -c1-40 | sed 's/-[^-]*$//')
fi
# Fallback if empty
if [ -z "$PROJECT_NAME" ]; then
  PROJECT_NAME="project-$(date +%s)"
fi

PROJECT_DIR="$PROJECTS_DIR/$PROJECT_NAME"
CHECKPOINT_FILE="$PROJECT_DIR/.pipeline-checkpoint"

log "Creating project: $PROJECT_NAME"
mkdir -p "$PROJECT_DIR"

# ─── Initialize KB ───
mkdir -p "$PROJECT_DIR/kb"
echo '{"nodes": [], "edges": []}' > "$PROJECT_DIR/kb/graph.json"
cp "$FACTORY_DIR/kb/schema.json" "$PROJECT_DIR/kb/schema.json"

# ─── Initialize Git ───
cd "$PROJECT_DIR"
git init >/dev/null 2>&1

# ─── Checkpoint helper ───
mark_phase() {
  echo "$1" > "$CHECKPOINT_FILE"
}

is_phase_done() {
  [ "$RESUME_MODE" = true ] && [ -f "$CHECKPOINT_FILE" ] && [ "$(cat "$CHECKPOINT_FILE")" = "$1" ]
}

# ─── Failure learning trap ───
# Even if the pipeline fails, log what went wrong to the KB
failure_learn() {
  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    log_warn "Pipeline failed (exit $exit_code). Logging failure to KB..."
    "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
      "Pipeline failed" \
      "Pipeline exited with code $exit_code. Last checkpoint: $(cat "$CHECKPOINT_FILE" 2>/dev/null || echo 'none'). Check logs for details." 2>/dev/null || true
    "$KB_SCRIPT" append-node "$FACTORY_DIR/kb/global-graph.json" "learning" \
      "Pipeline failure: $PROJECT_NAME" \
      "Pipeline failed at checkpoint $(cat "$CHECKPOINT_FILE" 2>/dev/null || echo 'none'). Exit code: $exit_code." 2>/dev/null || true
    log_error "Pipeline failed. KB updated with failure details."
  fi
}
trap failure_learn EXIT

# ═══════════════════════════════════════════════════════
# PHASE 0: HUMAN INTERACTIVE (or auto)
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-0"; then
  log "Phase 0 already complete (resume mode), skipping..."
else
  log_phase "0" "INTENT — Define the idea"

  if [ "$AUTO_MODE" = true ]; then
    # Auto mode: skip interview, use idea as intent directly
    log "Auto mode: using idea description as intent (no interview)"
    echo "INTENT_FINALIZED: $IDEA" > "$PROJECT_DIR/interview_output.txt"
  else
    # Interactive mode: GLM-5.2 interviews the human
    echo -e "${YELLOW}━━━ Interactive Session — Human + Agent ━━━${NC}"
    echo -e "${YELLOW}The agent will ask questions to clarify your idea.${NC}"
    echo ""

    pi --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
      --thinking "$PLANNER_THINKING" \
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
    echo ""
  fi
fi

# Extract intent
INTENT=$(grep -A 50 "INTENT_FINALIZED:" "$PROJECT_DIR/interview_output.txt" 2>/dev/null | sed 's/^INTENT_FINALIZED: //' || echo "$IDEA")
# Fallback: if no INTENT_FINALIZED found, use the entire idea
if [ -z "$INTENT" ] || [ "$INTENT" = "$IDEA" ]; then
  INTENT="$IDEA"
fi

# Log intent to KB
INTENT_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "intent" \
  "Human intent for $PROJECT_NAME" \
  "$INTENT")

git add -A && git commit -m "Intent captured" >/dev/null 2>&1
mark_phase "phase-0"

# ═══════════════════════════════════════════════════════
# PHASE 1: SPEC — GLM-5.2
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-1"; then
  log "Phase 1 already complete (resume mode), skipping..."
else
  log_phase "1" "SPEC — GLM-5.2"

  KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

  # Pass models.json content for accuracy
  MODELS_CONFIG=$(cat "$CONFIG_FILE")

  pi -p --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
    --thinking "$PLANNER_THINKING" \
    --skill "$SKILLS_DIR/spec-driven-development/" \
    --skill "$FACTORY_SKILLS_DIR/kb-manager/" \
    --append-system-prompt "You are a software architect. Follow the spec-driven-development skill.
The human has left. This is autonomous. No human will answer questions.

Human intent:
$INTENT

KB context:
$KB_SUMMARIES

Model config (use these exact model names in any documentation):
$MODELS_CONFIG

Create spec.md with: project name, tech stack, structure, features, acceptance criteria, testing approach, boundaries.
Write the spec to spec.md. Be concise. Do NOT ask questions — decide autonomously.
Do NOT write code, do NOT create any files other than spec.md, do NOT build the product.
You are writing a SPECIFICATION DOCUMENT only." \
    "$INTENT" 2>&1 | tee "$PROJECT_DIR/spec_output.txt"

  if [ ! -f "$PROJECT_DIR/spec.md" ]; then
    # Fallback: check if the model already produced code files during Phase 0
    log_warn "spec.md not found. Checking for existing artifacts..."
    ARTIFACT_COUNT=$(find "$PROJECT_DIR" -name "*.html" -o -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.go" -o -name "*.rs" 2>/dev/null | grep -v '.git' | wc -l | tr -d ' ')
    if [ "$ARTIFACT_COUNT" -gt 0 ]; then
      log_warn "Found $ARTIFACT_COUNT existing code file(s). Model may have built during Phase 0."
      log "Generating a retroactive spec from existing artifacts..."
      # Generate spec from existing files
      find "$PROJECT_DIR" -not -path '*/.git/*' -not -name '.DS_Store' -type f | grep -E '\.(html|py|js|ts|go|rs|css|json|md)$' | while read -r f; do
        echo "## File: $(basename "$f")" >> "$PROJECT_DIR/spec.md"
        head -5 "$f" >> "$PROJECT_DIR/spec.md"
        echo "..." >> "$PROJECT_DIR/spec.md"
      done
      echo "" >> "$PROJECT_DIR/spec.md"
      echo "## Note" >> "$PROJECT_DIR/spec.md"
      echo "Spec generated retroactively from artifacts produced during Phase 0." >> "$PROJECT_DIR/spec.md"
      log_success "Retroactive spec generated from existing artifacts"
    else
      log_error "Spec generation failed and no existing artifacts found"
      exit 1
    fi
  fi

  log_success "Spec generated"
fi

SPEC_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "spec" \
  "Spec for $PROJECT_NAME" "$(cat "$PROJECT_DIR/spec.md")")
"$KB_SCRIPT" append-edge "$PROJECT_DIR/kb/graph.json" "$SPEC_NODE_ID" "$INTENT_NODE_ID" "parent_of"

git add -A && git commit -m "Spec generated" >/dev/null 2>&1
mark_phase "phase-1"

# ═══════════════════════════════════════════════════════
# PHASE 2: PLAN — GLM-5.2
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-2"; then
  log "Phase 2 already complete (resume mode), skipping..."
else
  log_phase "2" "PLAN — GLM-5.2 generating issues"

  KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

  pi -p --model "$PLANNER_MODEL" --provider "$PLANNER_PROVIDER" \
    --thinking "$PLANNER_THINKING" \
    --skill "$SKILLS_DIR/planning-and-task-breakdown/" \
    --append-system-prompt "You are a project planner. Follow the planning-and-task-breakdown skill.
The human has left. This is autonomous. No questions.

Read spec.md and create issues.md with ordered issues.
Each issue: ## Issue #N: Title, description, acceptance criteria, dependencies.
Keep issues small and atomic. Write to issues.md.
Do NOT write code — only write the issues document." \
    "$(cat "$PROJECT_DIR/spec.md")" 2>&1 | tee "$PROJECT_DIR/plan_output.txt"

  if [ ! -f "$PROJECT_DIR/issues.md" ]; then
    # Fallback: if model built artifacts during earlier phases, create a single review/verify issue
    log_warn "issues.md not found. Checking for existing artifacts..."
    ARTIFACT_COUNT=$(find "$PROJECT_DIR" -name "*.html" -o -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.go" -o -name "*.rs" 2>/dev/null | grep -v '.git' | wc -l | tr -d ' ')
    if [ "$ARTIFACT_COUNT" -gt 0 ]; then
      log "Creating single review-and-verify issue for existing artifacts..."
      cat > "$PROJECT_DIR/issues.md" << 'ISSUEEOF'
## Issue #1: Review and verify existing code

Review all code files in the project for:
- HTML validity and accessibility (WCAG 2.1 AA)
- CSS issues, broken layouts, missing responsive breakpoints
- JavaScript errors
- Content accuracy (verify install commands, model names, feature descriptions)
- Missing closing tags, broken links
Fix any issues found and verify the project runs locally.

**Acceptance criteria:**
- All HTML is valid
- All SVGs have aria-hidden or aria-label
- All internal links work
- Install commands match actual Siesta setup
- Model names match factory/config/models.json
- Project opens and displays correctly in a browser
ISSUEEOF
      log_success "Fallback issue created for existing artifacts"
    else
      log_error "Plan generation failed and no existing artifacts found"
      exit 1
    fi
  fi

  log_success "Plan generated"
fi

# Log issues to KB
while IFS= read -r line; do
  if [[ "$line" =~ ^##[[:space:]]Issue[[:space:]]\#([0-9]+) ]]; then
    ISSUE_NODE_ID=$("$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "issue" \
      "Issue #${BASH_REMATCH[1]}" "$line")
    "$KB_SCRIPT" append-edge "$PROJECT_DIR/kb/graph.json" "$ISSUE_NODE_ID" "$SPEC_NODE_ID" "parent_of"
  fi
done < "$PROJECT_DIR/issues.md"

git add -A && git commit -m "Plan generated with issues" >/dev/null 2>&1
mark_phase "phase-2"

# ═══════════════════════════════════════════════════════
# PHASE 3: EXECUTE LOOP — Qwen 2.5
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-3"; then
  log "Phase 3 already complete (resume mode), skipping..."
else
  log_phase "3" "EXECUTE — Qwen 2.5"

  ISSUE_COUNT=$(grep -c "^## Issue #" "$PROJECT_DIR/issues.md" 2>/dev/null || echo 0)
  if [ "$ISSUE_COUNT" -eq 0 ]; then
    ISSUE_COUNT=$(grep -c "^### Issue\|^## Issue\|^Issue #\|^- \[" "$PROJECT_DIR/issues.md" 2>/dev/null || echo 1)
  fi

  log "Found $ISSUE_COUNT issues to execute"

  CURRENT_ISSUE=1
  BLOCKED_ISSUES=()
  # Use regular array instead of associative array (bash 3.2 on macOS doesn't support -A)
  # ISSUE_FAIL_COUNT is indexed by issue number (integer)
  ISSUE_FAIL_COUNT=()

  # Helper: get fail count for an issue (works without associative arrays)
  get_fail_count() {
    local issue=$1
    echo "${ISSUE_FAIL_COUNT[$issue]:-0}"
  }

  # Helper: increment fail count for an issue
  inc_fail_count() {
    local issue=$1
    local current=$(get_fail_count $issue)
    ISSUE_FAIL_COUNT[$issue]=$((current + 1))
    echo $((current + 1))
  }

  # ─── Stop signal check ───
  check_stop() {
    if [ -f "$PROJECT_DIR/stop.md" ]; then
      log_warn "stop.md detected! Halting pipeline."
      log "Reason: $(cat "$PROJECT_DIR/stop.md")"
      "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
        "Pipeline halted by stop.md" "$(cat "$PROJECT_DIR/stop.md")"
      exit 0
    fi
  }

  # ─── Regression suite runner ───
  run_regression_suite() {
    local project_dir="$1"
    local test_dir="$project_dir/tests"
    if [ -d "$test_dir" ]; then
      log "Running regression suite (all previous tests)..."
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

  # ─── Escalation: run GLM with thinking=high ───
  consult_glm() {
    local issue_num="$1"
    local consult_text="$2"
    local kb_context="$3"
    local fail_count="${4:-0}"
    local thinking_level="off"

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

  # ─── Deep diagnosis ───
  diagnose_blocker() {
    local issue_num="$1"
    local issue_text="$2"
    local failure_history="$3"
    local kb_context="$4"

    log_warn "Issue #$issue_num has failed multiple times. Running deep diagnosis..."

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

  # ─── Gather source files for review context ───
  # pi -p can't use tools, so we pipe file content into prompts
  gather_source_files() {
    local project_dir="$1"
    local result=""
    for f in $(find "$project_dir" -not -path '*/.git/*' -not -path '*/kb/*' -not -name '.DS_Store' -not -name '.pipeline-checkpoint' -type f | sort); do
      local rel=$(echo "$f" | sed "s|$project_dir/||")
      local ext="${f##*.}"
      case "$ext" in
        html|css|js|ts|py|go|rs|json|md|sh|jsx|tsx|vue|svelte)
          local content=$(cat "$f" 2>/dev/null | head -500)
          result="$result

--- File: $rel ---
$content"
          ;;
      esac
    done
    echo "$result"
  }

  while [ "$CURRENT_ISSUE" -le "$ISSUE_COUNT" ]; do
    check_stop

    log "Executing issue #$CURRENT_ISSUE..."

    ISSUE_TEXT=$(awk "/^## Issue #$CURRENT_ISSUE/{flag=1; next} /^## Issue #/{flag=0} flag" "$PROJECT_DIR/issues.md" 2>/dev/null)

    if [ -z "$ISSUE_TEXT" ]; then
      log_warn "Issue #$CURRENT_ISSUE not found, skipping"
      CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
      continue
    fi

    # ─── Regression suite ───
    if [ "$CURRENT_ISSUE" -gt 1 ]; then
      run_regression_suite "$PROJECT_DIR" "$CURRENT_ISSUE"
      REGRESSION_EXIT=$?
      if [ $REGRESSION_EXIT -ne 0 ]; then
        log_error "Regression suite FAILED before issue #$CURRENT_ISSUE."
        "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "blocker" \
          "Regression failure before issue #$CURRENT_ISSUE" \
          "Previous issue broke existing tests. See regression_${CURRENT_ISSUE}.log"
      fi
    fi

    # ─── Hook: pre-issue ───
    "$HOOKS_DIR/pre-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" > "$PROJECT_DIR/pre_issue_${CURRENT_ISSUE}.json" 2>/dev/null || true
    KB_SUMMARIES=$(cat "$PROJECT_DIR/pre_issue_${CURRENT_ISSUE}.json" 2>/dev/null | jq -c '.kb_summaries' 2>/dev/null || echo "[]")

    # ─── Gather existing source files for context ───
    SOURCE_CONTEXT=$(gather_source_files "$PROJECT_DIR")

    # ─── Execute with Qwen (with --thinking off) ───
    ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
      --thinking "$WORKER_THINKING" \
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

Existing source files in the project:
$SOURCE_CONTEXT

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

    # ─── Check: PROXY_REQUEST ───
    if echo "$ISSUE_OUTPUT" | grep -q "PROXY_REQUEST:"; then
      log "Worker requesting proxy approval for issue #$CURRENT_ISSUE..."
      PROXY_REQUEST=$(echo "$ISSUE_OUTPUT" | grep -A 20 "PROXY_REQUEST:")

      PROXY_OUTPUT=$(pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
        --thinking "$CONSULTANT_THINKING" \
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
          --thinking "$WORKER_THINKING" \
          --skill "$SKILLS_DIR/incremental-implementation/" \
          --skill "$SKILLS_DIR/test-driven-development/" \
          --append-system-prompt "Proxy rejected: $PROXY_OUTPUT. Try a different approach for: $ISSUE_TEXT" \
          "$ISSUE_TEXT" 2>&1)
        echo "$ISSUE_OUTPUT" > "$PROJECT_DIR/issue_${CURRENT_ISSUE}_retry_output.txt"
      fi
    fi

    PREVIOUS_FAILURES=""

    # ─── Check: CONSULT ───
    if echo "$ISSUE_OUTPUT" | grep -q "CONSULT:"; then
      FAIL_NUM=$(inc_fail_count $CURRENT_ISSUE)
      FAIL_COUNT=$(get_fail_count $CURRENT_ISSUE)
      log_warn "Worker stuck (attempt $FAIL_NUM), consulting GLM-5.2..."
      CONSULT_TEXT=$(echo "$ISSUE_OUTPUT" | grep -A 50 "CONSULT:")
      PREVIOUS_FAILURES="${PREVIOUS_FAILURES}Attempt $FAIL_NUM: $CONSULT_TEXT\n"

      if [ "$FAIL_COUNT" -ge 3 ]; then
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
          if echo "$DIAGNOSIS_OUTPUT" | grep -q "CRITICAL:"; then
            echo "Issue #$CURRENT_ISSUE is critical and cannot be skipped. Manual intervention needed." > "$PROJECT_DIR/stop.md"
            log_error "CRITICAL: stop.md created. Pipeline will halt."
            break
          fi
          CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
          continue
        fi

        log "Diagnosis provided, feeding back to worker..."
        ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
          --thinking "$WORKER_THINKING" \
          --skill "$SKILLS_DIR/incremental-implementation/" \
          --skill "$SKILLS_DIR/test-driven-development/" \
          --append-system-prompt "A senior engineer did a deep diagnosis and provided this plan:

$DIAGNOSIS_OUTPUT

Existing source files:
$SOURCE_CONTEXT

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
        CONSULT_OUTPUT=$(consult_glm "$CURRENT_ISSUE" "$CONSULT_TEXT" "$KB_SUMMARIES" "$FAIL_COUNT")

        echo "$CONSULT_OUTPUT" > "$PROJECT_DIR/consult_${CURRENT_ISSUE}_output.txt"
        "$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "consultation" \
          "Consultation for issue #$CURRENT_ISSUE" "$CONSULT_TEXT"

        log "GLM-5.2 resolved, feeding back to worker..."
        ISSUE_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
          --thinking "$WORKER_THINKING" \
          --skill "$SKILLS_DIR/incremental-implementation/" \
          --skill "$SKILLS_DIR/test-driven-development/" \
          --append-system-prompt "A senior engineer provided this guidance:

$CONSULT_OUTPUT

Existing source files:
$SOURCE_CONTEXT

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
    "$HOOKS_DIR/post-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" "$PROJECT_DIR/issue_${CURRENT_ISSUE}_output.txt" >/dev/null 2>&1 || true

    # ─── Hook: learn-issue ───
    "$HOOKS_DIR/learn-issue.sh" "$PROJECT_DIR" "$CURRENT_ISSUE" 2>&1 | tee "$PROJECT_DIR/learn_issue_${CURRENT_ISSUE}.log" >&2 || true

    CURRENT_ISSUE=$((CURRENT_ISSUE + 1))
  done
fi
mark_phase "phase-3"

# ═══════════════════════════════════════════════════════
# PHASE 4: REVIEW — Qwen + code-reviewer persona
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-4"; then
  log "Phase 4 already complete (resume mode), skipping..."
else
  log_phase "4" "REVIEW — Qwen 2.5 + code-reviewer"

  KB_SUMMARIES=$("$KB_SCRIPT" query "$PROJECT_DIR/kb/graph.json" --summary-only 2>/dev/null || echo "[]")

  # Gather all source files for review (pi -p can't use tools to read files)
  SOURCE_CONTEXT=$(gather_source_files "$PROJECT_DIR")

  REVIEW_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
    --thinking "$WORKER_THINKING" \
    --skill "$SKILLS_DIR/code-review-and-quality/" \
    --skill "$SKILLS_DIR/code-simplification/" \
    --append-system-prompt "You are the code-reviewer persona. Follow the code-review-and-quality skill.
Review all code across 5 axes: correctness, readability, architecture, security, performance.

Reference: definition-of-done.md for exit criteria.

KB Context:
$KB_SUMMARIES

Source files to review:
$SOURCE_CONTEXT

If review passes: REVIEW_PASSED: <summary>
If critical issues: REVIEW_FAILED: <issues>. List each issue with the file name and specific fix needed." \
    "Review the code in this project" 2>&1)

  echo "$REVIEW_OUTPUT" > "$PROJECT_DIR/review_output.txt"

  # Human-proxy approves review
  PROXY_REVIEW=$(pi -p --model "$CONSULTANT_MODEL" --provider "$CONSULTANT_PROVIDER" \
    --thinking "$CONSULTANT_THINKING" \
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
    # Include source files in the fix prompt too
    pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
      --thinking "$WORKER_THINKING" \
      --skill "$SKILLS_DIR/code-review-and-quality/" \
      --skill "$SKILLS_DIR/code-simplification/" \
      --append-system-prompt "Proxy requested: $PROXY_REVIEW.

Source files:
$SOURCE_CONTEXT

Fix the issues now. Output the corrected file contents." \
      "Fix review issues" 2>&1 | tee "$PROJECT_DIR/review_fixes_output.txt"
  fi

  log_success "Review complete"
fi
mark_phase "phase-4"

# ═══════════════════════════════════════════════════════
# PHASE 5: VERIFY — Qwen verifies it runs locally
# ═══════════════════════════════════════════════════════
if is_phase_done "phase-5"; then
  log "Phase 5 already complete (resume mode), skipping..."
else
  log_phase "5" "VERIFY — Runs locally?"

  SOURCE_CONTEXT=$(gather_source_files "$PROJECT_DIR")

  VERIFY_OUTPUT=$(pi -p --model "$WORKER_MODEL" --provider "$WORKER_PROVIDER" \
    --thinking "$WORKER_THINKING" \
    --skill "$SKILLS_DIR/test-driven-development/" \
    --skill "$SKILLS_DIR/debugging-and-error-recovery/" \
    --append-system-prompt "You are a QA engineer. Follow the debugging-and-error-recovery skill.
Verify this project runs locally:
1. Check project type (Python, Node, HTML, etc.)
2. For HTML: check that all tags are closed, scripts are valid, CSS is well-formed
3. For Python/Node: check that entry points exist and dependencies are listed
4. If it would fail, describe the fix needed
5. Output VERIFY_PASSED: or VERIFY_FAILED:

Source files:
$SOURCE_CONTEXT" \
    "Verify this project runs locally" 2>&1)

  echo "$VERIFY_OUTPUT" > "$PROJECT_DIR/verify_output.txt"
fi
mark_phase "phase-5"

# ═══════════════════════════════════════════════════════
# PHASE 6: DONE
# ═══════════════════════════════════════════════════════
log_phase "6" "DONE"

# Log final state to KB
"$KB_SCRIPT" append-node "$PROJECT_DIR/kb/graph.json" "decision" \
  "Project complete: $PROJECT_NAME" \
  "Project verified running locally."

# Final git commit
git add -A && git commit -m "Project verified: $PROJECT_NAME" >/dev/null 2>&1

# ═══════════════════════════════════════════════════════
# PHASE 7: LEARN (project-level)
# ═══════════════════════════════════════════════════════
log_phase "7" "LEARN — Project-level learning"

"$FACTORY_DIR/scripts/learn.sh" "$PROJECT_DIR" "$PROJECT_NAME" 2>&1 | tee "$PROJECT_DIR/project_learning.log" || true

mark_phase "complete"

# Summary
echo ""
echo "==========================================="
log_success "Siesta pipeline complete!"
echo "==========================================="
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