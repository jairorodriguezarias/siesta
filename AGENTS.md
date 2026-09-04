# AGENTS.md — Siesta Agent System

This document describes the autonomous agent system that powers Siesta: the roles, how they interact, the skills they use, and the knowledge base that connects them.

---

## Overview

Siesta uses a **dual-model architecture**: GLM 5.2 (via `pi`, Ollama Cloud) plays the roles that must hold the text protocol — planner, consultant, human-proxy — while the fully local Qwen 2.5 Coder (Ollama) is the worker that writes, reviews and verifies code. A pipeline orchestrator (`python3 -m pipeline`) coordinates them across 7 phases, with per-issue context loading, post-issue logging, and per-issue learning.

```
┌─────────────────────────────────────────────────────────────┐
│                  python3 -m pipeline                         │
│                   (Orchestrator - Phase 0-7)                  │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  GLM 5.2     │    │  Qwen 2.5    │    │  GLM 5.2      │  │
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

### 1. Planner — GLM 5.2 (via pi)

**When:** Phases 0, 1, 2

**Responsibilities:**
- **Phase 0 (Interview):** Asks the human one question at a time until ~95% confidence about what to build. When confident, outputs `INTENT_FINALIZED:`. The human then leaves.
- **Phase 1 (Spec):** Autonomously writes `spec.md` with: project name, tech stack, structure, features, acceptance criteria, testing approach, boundaries. No questions — decides alone.
- **Phase 2 (Plan):** Reads the spec and writes `issues.md` with ordered, atomic issues. Each issue has: title, description, acceptance criteria, dependencies.

**Skills used:**
- `interview-me` (Phase 0)
- `spec-driven-development` (Phase 1)
- `planning-and-task-breakdown` (Phase 2)

**KB interaction:** Loads standing architectural principles from the global KB before writing the spec (they are mandatory for every project). Logs the human intent as a node, then the spec as a node, then each issue as a node, with `parent_of` edges linking them.

---

### 2. Worker — Qwen 2.5 Coder

**When:** Phase 3 (Execute), Phase 4 (Review), Phase 5 (Verify)

**Responsibilities:**
- **Phase 3:** Executes each issue following TDD (Red → Green → Refactor). Writes code and tests. If stuck, outputs `CONSULT:` with a specific question, context, and code. If a skill says "ask the human", outputs `PROXY_REQUEST:`.
- **Phase 4:** Reviews all code across 5 axes: correctness, readability, architecture, security, performance. Outputs `REVIEW_PASSED:` or `REVIEW_FAILED:`.
- **Phase 5:** Verifies the project runs locally. Detects project type (incl. packages with `__main__.py`, run as `python -m <pkg>`), tries to run it, fixes if needed. Persists the verdict to `verify_verdict.txt` — phase 6 records decision+commit or blocker+`UNVERIFIED` commit per the real verdict.

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

**KB interaction:** Queries KB summaries before each issue (`phases.pre_issue()`). The pre-issue context also includes the global KB's standing architectural principles — the worker must respect them in every issue. Logs decisions and learnings via `phases.post_issue()`.

---

### 3. Consultant — GLM 5.2 (via pi)

**When:** Phase 3 (when worker outputs `CONSULT:`)

**Responsibilities:**
- Receives the worker's question, context, and code
- Loads KB context for the current issue
- Performs adversarial review (CLAIM → EXTRACT → DOUBT → RECONCILE → STOP)
- Returns a resolution with `RESOLUTION:`, `APPROACH:`, `CODE:`, `CONFIDENCE:`
- If confidence is low, outputs `ESCALATE: web search needed for <query>`
- If web search also fails, logs as blocker and the issue is skipped

**Escalation ladder:**
1. Normal consultation (one resolution-guided retry)
2. After 2 failures: a second resolution-guided retry
3. After 3 failures: **Deep diagnosis** — root-cause analysis, can recommend SKIP
4. If diagnosis says `CRITICAL:` → `stop.md` is created, pipeline halts

**Skills used:**
- `consultant-protocol` (factory custom)
- `human-proxy` (for deep diagnosis only)
- `kb-manager` (factory custom)

**KB interaction:** Logs each consultation. If the consultation resolved a blocker, logs the resolution as a decision.

---

### 4. Human-Proxy — GLM 5.2 (consultant role, via pi)

**When:** Phase 3 (when worker outputs `PROXY_REQUEST:`), Phase 4 (review approval)

**Responsibilities:**
- Replaces the human in autonomous phases. The human already left — their intent is in the KB.
- Loads the original human intent, spec, and all prior decisions from the KB
- Evaluates the request against: alignment with intent, scope, simplicity, risk, consistency
- Outputs `APPROVED`, `REJECTED`, or `NEEDS_REVISION` with reasoning and KB evidence — as a line-start marker (the gate is fail-closed: unmarked output is never approval)
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

**Per-issue learning (Level 1):** Runs immediately after each issue via `learn.learn_issue()`:
- Did I get stuck? Why? → Add Red Flag to `issue-executor` skill
- Was I rejected by the proxy? Why? → Add to Rationalizations table
- What decision did I make? Is it a pattern? → Log to global KB
- What went well? → Log as best practice
- Novel pattern not covered by any skill? → Create new factory skill

**Project-level learning (Level 2):** Runs once at project end via `learn.learn_project()`:
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
pre_issue() → Worker (Qwen) → post_issue() → learn_issue()
     │              │                │                │
     ▼              │                ▼                ▼
  Load KB       Implement       Git commit     Learn & improve
  context       + tests         + log to KB    skills
```

**Guards around the loop (silence is not success):**

- **Degenerate-output guard** (`text.degenerate()`): a worker answer that is
  tool-call JSON, asks the absent human for input, or is truncated is not an
  execution. It gets one feedback retry; if it stays degenerate the issue is
  blocked and logged to the KB — never recorded as completed.
- **Regression gating**: the suite re-runs before each new issue. A red suite
  skips the next issue (blocked) instead of building on a broken base, and
  "no tests at all" is reported as `skipped` — never as green.
- **Verify fallback**: with no usable VERIFY marker, only the mechanical
  checks decide (regression suite + runtime smoke); no tests means failed.
- **Call timeout** (`pi.PI_TIMEOUT`, env `SIESTA_PI_TIMEOUT`, 1200s default):
  a hung `pi`/Ollama call returns empty and counts as a failed attempt —
  the degenerate guards already handle it. `stop.md` only works between
  issues, so a timeout is the only defense against a frozen call.
- **Explicit approval marker** (`text.APPROVED`): anchored to line start
  (optional `PROXY_DECISION:` prefix). Both proxy gates are fail-closed —
  explicit `APPROVED` continues, `REJECTED` retries with a different
  approach, and `NEEDS_REVISION` / hesitation / garbage retry with feedback.
  Unmarked output can never count as approval, and an accidental mention of
  `NEEDS_REVISION` inside prose cannot trigger a revision.
- **Review-fix with write tools**: the proxy-requested fix pass runs with
  write tools (like the execute phase) so fixes actually land in files and
  are committed afterwards; degenerate fix output only warns.
- **Per-issue idempotent resume**: `execute()` skips issues whose
  "Issue #N completed" decision node is already on disk; blocked issues
  have no node, so they naturally retry on resume.
- **Spec relevance guard** (`text.shares_content()`): a spec sharing zero
  content words with the interview intent is rejected as a template
  hallucination — one `SPEC_RETRY_DIRECTIVE` retry, then abort.
- **Planner retries**: a plan without `## Issue #N:` headers gets one
  `PLAN_RETRY_DIRECTIVE` retry demanding the exact format before the
  fallbacks. Both prompts forbid generic templates and priority groupings.
- **Honest verify verdict**: `verify()` persists its verdict to
  `verify_verdict.txt`; resume reads it instead of hardcoding
  `VERIFY_PASSED`, and phase 6 ties the decision node + commit message to
  the real verdict (failed verify → blocker node + `UNVERIFIED` commit).
- **Generated hygiene**: project init writes a standard `.gitignore`
  (`.DS_Store`, `__pycache__/`, `*.pyc`, checkpoint, `verify_verdict.txt`)
  before the first `git add -A`.

### Worker Gets Stuck

```
Worker → CONSULT: → Consultant → RESOLUTION: → Worker retries
  │                                            │
  │  (if 2nd failure)                          │
  └→ CONSULT: → Consultant → ─────────────────┘
  │
  │  (if 3rd failure)
  └→ Deep diagnosis (consultant role)
       ├→ DIAGNOSIS: fix → Worker retries with plan
       └→ SKIP: → Log blocker, skip issue, continue pipeline
```

### Worker Needs Human Approval

```
Worker → PROXY_REQUEST: → Human-proxy (consultant role)
                               ├→ APPROVED (line-start marker) → Worker continues
                               ├→ REJECTED → Worker tries different approach
                               └→ NEEDS_REVISION / unmarked → Worker adjusts, resubmits with feedback
```

### Deep Diagnosis (after 3 failures)

```
diagnose_blocker (consultant role)
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

### KB Operations (via `python3 -m pipeline.kb`)

```bash
# Query summaries (cheapest; run from factory/ or set PYTHONPATH=factory)
python3 -m pipeline.kb query kb/graph.json --summary-only

# Query specific type
python3 -m pipeline.kb query kb/graph.json --type decision --summary-only

# Get full node detail
python3 -m pipeline.kb get-node kb/graph.json n1695234567_12345

# Append a decision
python3 -m pipeline.kb append-node kb/graph.json "decision" "Summary" "Full detail"

# Link two nodes
python3 -m pipeline.kb append-edge kb/graph.json n123 n456 applied_to

# Initialize fresh KB
python3 -m pipeline.kb init-project kb/graph.json
```

### Two KB Tiers

| KB | Location | Scope | Purpose |
|----|----------|-------|---------|
| Project KB | `factory/projects/<name>/kb/graph.json` | One project | Track decisions, blockers, consultations for this project |
| Global KB | `factory/kb/global-graph.json` | All projects | Standing architectural principles (node type `principle`) plus accumulated learnings across projects — the factory's long-term memory |

### Standing Architectural Principles

The global KB holds `principle` nodes — standing rules that constrain every project. They are injected automatically into the Phase 1 spec prompt and into every per-issue worker context (`phases.pre_issue()`). Current principles (query with `python3 -m pipeline.kb query factory/kb/global-graph.json --type principle --summary-only`):

1. Personal projects only — runs entirely on the local computer, minimal infrastructure
2. Simplicity is the core rule — fewer lines of code wins
3. Code must explain itself
4. Python is the default language
5. Use english — docs, KB content and code comments
6. Verify pushes contain no PI — `.pi/` stays ignored; no personal information in commits

To change them: update the `principle` nodes in the global KB — every pipeline run reads them fresh.

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

### Skill Locations

All skills are tracked in this repository
([https://github.com/jairorodriguezarias/siesta](https://github.com/jairorodriguezarias/siesta)) —
a fresh clone brings the 15 sources; no separate skill-install step exists. There
are no runtime view folders: `run_pi()` loads each skill with an explicit
`--skill <path>` flag pointing at the tracked sources. `.pi/` and `.claude/`
remain in `.gitignore` only as guards (the `pi` CLI can write runtime state
there). `setup-github.sh` is a legacy one-shot migration script — deprecated.
The learner may only touch `factory/skills/`.

### Skill Categories

**Addyosmani skills (10, tailoring allowed):**
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

The learner can modify factory skills (add Red Flags, Rationalizations, Process steps, Verification checks) but never touches addyosmani skills — manual factory adaptations to addyosmani skills (e.g. the autonomous no-tools output protocol) are made by the human directly in `.agents/skills/`.

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

Each role also carries a `skills` list documenting the skills `run_pi()` loads
for it — kept in sync with the actual `run_pi(..., skills=(...))` calls in
`phases.py` / `learn.py`. The pipeline itself only reads `model` and `provider`.

### Timeouts

`SIESTA_PI_TIMEOUT` (seconds, default 1200) caps every `pi` call — see the call-timeout guard above.

### KB Schema

[`factory/kb/schema.json`](factory/kb/schema.json) — Defines valid node types and edge types. Used by `pipeline/kb.py` (the `Graph` store) to validate node types before appending.

---

## Extending Siesta

### Add a new factory skill

1. Create `factory/skills/<skill-name>/SKILL.md` with the standard format
2. Commit it — a fresh clone of the repo must bring the new skill
3. Reference it in the pipeline via `FACTORY_SKILLS / "<skill-name>"` in `factory/pipeline/phases.py`
4. The factory-learner may automatically create skills if it detects novel patterns

### Change model routing

Edit `factory/config/models.json`. The pipeline reads this at startup. You can use any Ollama-compatible model.

### Add a new KB node type

1. Add it to `factory/kb/schema.json` under `node_types`
2. Use it in `python3 -m pipeline.kb append-node` calls
3. Query it with `python3 -m pipeline.kb query <graph> --type <new_type>`

### Add a new pipeline phase

Edit `factory/pipeline/phases.py` — each phase is a Python function. Add a `phaseN()` function, then wire it into the dispatch in `factory/pipeline/__main__.py` (following the skip/resume pattern of the existing phases). Use `phase(N, "TITLE")` from `pipeline.pi` for consistent output.

---

## File Index

| File | Purpose |
|------|---------|
| `factory/bin/siesta.sh` | Entry point — takes idea, runs pipeline |
| `factory/pipeline.log` | Full orchestrator narration, tee'd from the console (runtime, gitignored) |
| `factory/pipeline/__main__.py` | Orchestrator — checkpoint, failure trap, phase dispatch, summary |
| `factory/pipeline/phases.py` | Phase bodies 0-7 (interview, spec, plan, execute ladder, review, verify + runtime smoke) |
| `factory/pipeline/learn.py` | Per-issue micro-learning + project-level learning (Phase 7) |
| `factory/pipeline/pi.py` | Single `run_pi()` wrapper — every model call |
| `factory/pipeline/kb.py` | KB graph store + `python3 -m pipeline.kb` CLI shim |
| `factory/pipeline/text.py` | Anchored marker regexes + pure parsers |
| `factory/tests/` | Unit + fake-pi integration tests (`python3 -m unittest discover -s tests`) |
| `factory/BACKLOG.md` | Findings + corrections backlog — also the changelog of what Siesta learned about itself |
| `factory/config/models.json` | Model routing config |
| `setup-github.sh` | Legacy one-shot migration script (path fixes, old .gitignore, embedded README heredoc) — deprecated, unrelated to skill loading |
| `factory/kb/schema.json` | KB node/edge type schema |
| `factory/kb/global-graph.json` | Cross-project accumulated learnings |
| `factory/skills/*/SKILL.md` | 5 custom factory skills |
| `.agents/skills/*/SKILL.md` | 10 addyosmani skills (with factory-tailoring sections) |
| `.agents/agents/code-reviewer.md` | Code reviewer persona |
| `.agents/references/definition-of-done.md` | Standing done checklist |
| `.agents/references/security-checklist.md` | Security quick reference |