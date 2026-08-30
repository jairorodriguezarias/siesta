# AGENTS.md — Siesta Agent System

This document describes the autonomous agent system that powers Siesta: the roles, how they interact, the skills they use, and the knowledge base that connects them.

---

## Overview

Siesta uses a **dual-model architecture** with two Ollama models playing distinct roles. A pipeline orchestrator (`run-pipeline.sh`) coordinates them across 7 phases, with hooks for pre-issue context loading, post-issue logging, and per-issue learning.

```
┌─────────────────────────────────────────────────────────────┐
│                     run-pipeline.sh                          │
│                   (Orchestrator - Phase 0-7)                  │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  GLM-5.2     │    │  Qwen 2.5    │    │  GLM-5.2      │  │
│  │  (Planner)   │    │  (Worker)    │    │  (Consultant) │  │
│  │              │    │              │    │               │  │
│  │ • Interview  │    │ • Execute    │    │ • Resolve     │  │
│  │ • Spec       │    │   issues     │───→│   doubts      │  │
│  │ • Plan       │    │ • Review     │    │ • Deep        │  │
│  │ • Proxy      │    • • Verify     │    │   diagnosis   │  │
│  └──────────────┘    └──────────────┘    └───────────────┘  │
│         │                   │                   │           │
│         └───────────────────┼───────────────────┘           │
│                             ▼                               │
│                    ┌──────────────┐                         │
│                    │  KB Graph    │                         │
│                    │  (JSON)      │                         │
│                    │  per-project │                         │
│                    │  + global    │                         │
│                    └──────────────┘                         │
│                             │                               │
│                             ▼                               │
│                    ┌──────────────┐                         │
│                    │  Learner     │                         │
│                    │  (Qwen 2.5)  │                         │
│                    │              │                         │
│                    │ • Per-issue  │                         │
│                    │   learning   │                         │
│                    │ • Skill      │                         │
│                    │   updates    │                         │
│                    └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Agent Roles

### 1. Planner — GLM-5.2

**When:** Phases 0, 1, 2

**Responsibilities:**
- **Phase 0 (Interview):** Asks the human one question at a time until ~95% confidence about what to build. When confident, outputs `INTENT_FINALIZED:`. The human then leaves.
- **Phase 1 (Spec):** Autonomously writes `spec.md` with: project name, tech stack, structure, features, acceptance criteria, testing approach, boundaries. No questions — decides alone.
- **Phase 2 (Plan):** Reads the spec and writes `issues.md` with ordered, atomic issues. Each issue has: title, description, acceptance criteria, dependencies.

**Skills used:**
- `interview-me` (Phase 0)
- `spec-driven-development` (Phase 1)
- `planning-and-task-breakdown` (Phase 2)

**KB interaction:** Logs the human intent as a node, then the spec as a node, then each issue as a node, with `parent_of` edges linking them.

---

### 2. Worker — Qwen 2.5 Coder

**When:** Phase 3 (Execute), Phase 4 (Review), Phase 5 (Verify)

**Responsibilities:**
- **Phase 3:** Executes each issue following TDD (Red → Green → Refactor). Writes code and tests. If stuck, outputs `CONSULT:` with a specific question, context, and code. If a skill says "ask the human", outputs `PROXY_REQUEST:`.
- **Phase 4:** Reviews all code across 5 axes: correctness, readability, architecture, security, performance. Outputs `REVIEW_PASSED:` or `REVIEW_FAILED:`.
- **Phase 5:** Verifies the project runs locally. Detects project type, tries to run it, fixes if needed.

**Skills used:**
- `incremental-implementation` (Phase 3)
- `test-driven-development` (Phase 3)
- `debugging-and-error-recovery` (Phase 3, 5)
- `issue-executor` (Phase 3 — factory custom)
- `code-review-and-quality` (Phase 4)
- `code-simplification` (Phase 4)

**Stuck protocol:**
```
CONSULT: <specific question>
CONTEXT: <what was tried>
CODE: <relevant code or error>
```
The orchestrator routes this to the Consultant. The worker does NOT guess.

**KB interaction:** Queries KB summaries before each issue (`pre-issue.sh`). Logs decisions and learnings via `post-issue.sh`.

---

### 3. Consultant — GLM-5.2

**When:** Phase 3 (when worker outputs `CONSULT:`)

**Responsibilities:**
- Receives the worker's question, context, and code
- Loads KB context for the current issue
- Performs adversarial review (CLAIM → EXTRACT → DOUBT → RECONCILE → STOP)
- Returns a resolution with `RESOLUTION:`, `APPROACH:`, `CODE:`, `CONFIDENCE:`
- If confidence is low, outputs `ESCALATE: web search needed for <query>`
- If web search also fails, logs as blocker and the issue is skipped

**Escalation ladder:**
1. Normal consultation (thinking=off)
2. After 2 failures: thinking escalates to `high`
3. After 3 failures: **Deep diagnosis** — root-cause analysis, can recommend SKIP
4. If diagnosis says `CRITICAL:` → `stop.md` is created, pipeline halts

**Skills used:**
- `consultant-protocol` (factory custom)
- `human-proxy` (for deep diagnosis only)
- `kb-manager` (factory custom)

**KB interaction:** Logs each consultation. If the consultation resolved a blocker, logs the resolution as a decision.

---

### 4. Human-Proxy — GLM-5.2

**When:** Phase 3 (when worker outputs `PROXY_REQUEST:`), Phase 4 (review approval)

**Responsibilities:**
- Replaces the human in autonomous phases. The human already left — their intent is in the KB.
- Loads the original human intent, spec, and all prior decisions from the KB
- Evaluates the request against: alignment with intent, scope, simplicity, risk, consistency
- Outputs `APPROVED`, `REJECTED`, or `NEEDS_REVISION` with reasoning and KB evidence
- Does NOT invent new requirements — only evaluates against existing intent

**Decision categories:**

| Skill says... | Proxy evaluates... | Proxy decides... |
|---|---|---|
| "Confirm approach with user" | Is the approach aligned with spec? | APPROVED or NEEDS_REVISION |
| "Wait for user approval" | Is the work complete per acceptance criteria? | APPROVED or REJECTED |
| "Ask user for clarification" | Can the KB answer this? | Answer from KB, or best guess |
| "User should review before merge" | Does the code meet the Definition of Done? | APPROVED or NEEDS_REVISION |

**Skills used:**
- `human-proxy` (factory custom)
- `kb-manager` (factory custom)

**KB interaction:** Every proxy decision is logged as a `proxy_decision` node. If rejected, also logs a `blocker` node with the reason.

---

### 5. Learner — Qwen 2.5

**When:** After every issue (Phase 3 hook), and at project end (Phase 7)

**Responsibilities:**

**Per-issue learning (Level 1):** Runs immediately after each issue via `learn-issue.sh`:
- Did I get stuck? Why? → Add Red Flag to `issue-executor` skill
- Was I rejected by the proxy? Why? → Add to Rationalizations table
- What decision did I make? Is it a pattern? → Log to global KB
- What went well? → Log as best practice
- Novel pattern not covered by any skill? → Create new factory skill

**Project-level learning (Level 2):** Runs once at project end via `learn.sh`:
- Which issues had blockers? Were they related?
- Which consultations were most valuable?
- Cross-issue patterns?
- Should any factory skill be restructured?
- Summary of all learnings → global KB

**Skills used:**
- `factory-learner` (factory custom)
- `kb-manager` (factory custom)

**KB interaction:** Logs learnings, blockers, consultations, and skill improvements to the global KB. Can modify factory skills (but never addyosmani skills).

---

### 6. Code Reviewer — Qwen 2.5 (persona)

**When:** Phase 4

**Responsibilities:**
- Reviews all code across 5 dimensions: correctness, readability, architecture, security, performance
- Categorizes findings: Critical, Required, Optional, Nit
- Always includes what's done well
- Verdict: APPROVE or REQUEST CHANGES

**Persona definition:** [`.agents/agents/code-reviewer.md`](.agents/agents/code-reviewer.md)

---

## Interaction Flows

### Normal Issue Execution

```
pre-issue.sh → Worker (Qwen) → post-issue.sh → learn-issue.sh
     │              │                │                │
     ▼              │                ▼                ▼
  Load KB       Implement       Git commit     Learn & improve
  context       + tests         + log to KB    skills
```

### Worker Gets Stuck

```
Worker → CONSULT: → Consultant (GLM) → RESOLUTION: → Worker retries
  │                                                    │
  │  (if 2nd failure)                                  │
  └→ CONSULT: → Consultant (thinking=high) → ─────────┘
  │
  │  (if 3rd failure)
  └→ Deep diagnosis (GLM thinking=high)
       ├→ DIAGNOSIS: fix → Worker retries with plan
       └→ SKIP: → Log blocker, skip issue, continue pipeline
```

### Worker Needs Human Approval

```
Worker → PROXY_REQUEST: → Human-proxy (GLM)
                               ├→ APPROVED → Worker continues
                               ├→ REJECTED → Worker tries different approach
                               └→ NEEDS_REVISION → Worker adjusts and re-submits
```

### Deep Diagnosis (after 3 failures)

```
diagnose_blocker (GLM, thinking=high)
  ├→ Root cause identified + fix plan → Worker implements fix
  ├→ SKIP: → Log blocker, skip issue, continue
  └→ CRITICAL: → Create stop.md, halt pipeline
```

---

## Knowledge Base (KB)

### Structure

The KB is a JSON graph stored in files:

```json
{
  "nodes": [
    {
      "id": "n1695234567_12345",
      "type": "decision",
      "summary": "Used argparse for CLI parsing",
      "detail": "Qwen chose argparse over click for zero dependencies...",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "edges": [
    {
      "from": "n1695234567_12345",
      "to": "n1695234567_67890",
      "type": "applied_to",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

### Progressive Disclosure

Agents don't load the full KB. They load in levels:

| Level | What | Cost | When |
|-------|------|------|------|
| 1 — Summary only | `{id, type, summary}` | Minimal tokens | Before every issue |
| 2 — Filtered by type | All decisions, or all blockers | Low | When looking for specific patterns |
| 3 — Full node | Complete detail field | Higher | When a specific node is relevant |

### KB Operations (via `kb-manager.sh`)

```bash
# Query summaries (cheapest)
kb-manager.sh query kb/graph.json --summary-only

# Query specific type
kb-manager.sh query kb/graph.json --type decision --summary-only

# Get full node detail
kb-manager.sh get-node kb/graph.json n1695234567_12345

# Append a decision
kb-manager.sh append-node kb/graph.json "decision" "Summary" "Full detail"

# Link two nodes
kb-manager.sh append-edge kb/graph.json n123 n456 applied_to

# Initialize fresh KB
kb-manager.sh init-project kb/graph.json
```

### Two KB Tiers

| KB | Location | Scope | Purpose |
|----|----------|-------|---------|
| Project KB | `factory/projects/<name>/kb/graph.json` | One project | Track decisions, blockers, consultations for this project |
| Global KB | `factory/kb/global-graph.json` | All projects | Accumulated learnings across projects; the factory's long-term memory |

---

## Skills System

### How Skills Work

Each skill is a `SKILL.md` file with YAML frontmatter and markdown body:

```markdown
---
name: skill-name
description: When to use this skill and what it does
---

# Skill Name

## When to Use
...

## Process
1. Step one
2. Step two
...

## Common Rationalizations
| Rationalization | Reality |
|---|---|
| "Excuse" | "Why it's wrong" |

## Red Flags
- Pattern that indicates a problem

## Verification
- [ ] Checklist item
```

Skills are loaded by the Pi agent via `--skill` flags. The agent follows the skill's process, avoids rationalizations, watches for red flags, and checks the verification gate.

### Skill Categories

**Addyosmani skills (10, unmodified):**
- `interview-me` — Structured interview to clarify intent
- `spec-driven-development` — Write specs with acceptance criteria
- `planning-and-task-breakdown` — Break specs into atomic issues
- `incremental-implementation` — Thin vertical slices, safe defaults
- `test-driven-development` — Red → Green → Refactor
- `debugging-and-error-recovery` — Systematic debugging
- `code-review-and-quality` — 5-axis code review
- `code-simplification` — Reduce complexity without changing behavior
- `git-workflow-and-versioning` — Atomic commits, clean history
- `using-agent-skills` — Meta-skill for skill usage

**Factory skills (5, custom, self-improving):**
- `issue-executor` — Worker's playbook per issue
- `consultant-protocol` — Consultant's playbook for resolving doubts
- `human-proxy` — Replaces human approval using KB context
- `kb-manager` — KB graph operations with progressive disclosure
- `factory-learner` — Per-issue and project-level learning

The learner can modify factory skills (add Red Flags, Rationalizations, Process steps, Verification checks) but never touches addyosmani skills.

---

## References

### Definition of Done

[`.agents/references/definition-of-done.md`](.agents/references/definition-of-done.md) — The standing checklist every change must clear before counting as done. Covers correctness, quality, integration, documentation, and ship-readiness.

### Security Checklist

[`.agents/references/security-checklist.md`](.agents/references/security-checklist.md) — Quick reference for web application security including threat modeling, authentication, input validation, security headers, CORS, data protection, and OWASP Top 10.

---

## Configuration

### Model Routing

[`factory/config/models.json`](factory/config/models.json):

```json
{
  "planner":    { "model": "glm-5.2:cloud",       "provider": "ollama" },
  "worker":     { "model": "qwen2.5-coder:latest", "provider": "ollama" },
  "consultant": { "model": "glm-5.2:cloud",       "provider": "ollama" },
  "fallback":   { "method": "web-search",         "package": "npm:@ollama/pi-web-search" }
}
```

### KB Schema

[`factory/kb/schema.json`](factory/kb/schema.json) — Defines valid node types and edge types. Used by `kb-manager.sh` to validate node types before appending.

---

## Extending Siesta

### Add a new factory skill

1. Create `factory/skills/<skill-name>/SKILL.md` with the standard format
2. Symlink it for Pi: `ln -s ../../factory/skills/<skill-name> .pi/skills/<skill-name>`
3. Reference it in the pipeline via `--skill "$FACTORY_SKILLS_DIR/<skill-name>/"`
4. The factory-learner may automatically create skills if it detects novel patterns

### Change model routing

Edit `factory/config/models.json`. The pipeline reads this at startup. You can use any Ollama-compatible model.

### Add a new KB node type

1. Add it to `factory/kb/schema.json` under `node_types`
2. Use it in `kb-manager.sh append-node` calls
3. Query it with `kb-manager.sh query <graph> --type <new_type>`

### Add a new pipeline phase

Edit `factory/scripts/run-pipeline.sh`. The phases are sequential bash blocks. Add your phase between existing ones. Use `log_phase` for consistent output.

---

## File Index

| File | Purpose |
|------|---------|
| `factory/bin/siesta.sh` | Entry point — takes idea, runs pipeline |
| `factory/scripts/run-pipeline.sh` | 7-phase orchestrator |
| `factory/scripts/learn.sh` | Project-level learning (Phase 7) |
| `factory/scripts/kb-manager.sh` | KB graph CRUD operations |
| `factory/hooks/pre-issue.sh` | Load KB context before each issue |
| `factory/hooks/post-issue.sh` | Log decision + git commit after each issue |
| `factory/hooks/learn-issue.sh` | Per-issue micro-learning |
| `factory/config/models.json` | Model routing config |
| `factory/kb/schema.json` | KB node/edge type schema |
| `factory/kb/global-graph.json` | Cross-project accumulated learnings |
| `factory/skills/*/SKILL.md` | 5 custom factory skills |
| `.agents/skills/*/SKILL.md` | 10 addyosmani skills (intact) |
| `.agents/agents/code-reviewer.md` | Code reviewer persona |
| `.agents/references/definition-of-done.md` | Standing done checklist |
| `.agents/references/security-checklist.md` | Security quick reference |