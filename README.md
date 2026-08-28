# Siesta

**"Give me an idea, go take a siesta, come back to working code."**

Siesta is a local-first autonomous development pipeline for macOS. You give it a project idea, answer a few clarifying questions, then walk away. When you come back, there's a git repository with working, tested code that runs locally.

No cloud APIs. No external services. Everything runs on your machine using [Ollama](https://ollama.ai) local models and the [Pi](https://github.com/mariozechner/pi-coding-agent) coding agent.

---

## How It Works

```
You:  "Build me a CLI pomodoro timer in Python"
      ↓
Phase 0: GLM-5.2 interviews you about what you want
         You answer. You leave. 💤
      ↓
Phase 1: GLM-5.2 writes the spec autonomously
Phase 2: GLM-5.2 breaks it into ordered issues
Phase 3: Qwen 2.5 Coder executes each issue:
         ├─ Writes code + tests (TDD: Red → Green → Refactor)
         ├─ Stuck? → GLM-5.2 consults (thinking escalates after 3 fails)
         ├─ 3 fails? → Deep diagnosis (root-cause analysis)
         ├─ Need approval? → Human-proxy (GLM-5.2) decides based on KB
         ├─ Regression suite runs before each new issue
         └─ Learns from every issue immediately
Phase 4: Qwen reviews code, human-proxy approves
Phase 5: Qwen verifies project runs locally
Phase 6: Final git commit
Phase 7: Qwen learns from the full project, improves skills
      ↓
You:  Come back. Working code. Git history. KB of decisions. 🎉
```

---

## Architecture

### Models (all local via Ollama)

| Model | Role | When |
|-------|------|------|
| **GLM-5.2** | Planner + Consultant + Human-proxy | Spec, plan, resolve doubts, approve decisions |
| **Qwen 2.5 Coder** | Worker + Reviewer + Learner | Execute issues, review code, learn from results |

Model routing is configured in [`factory/config/models.json`](factory/config/models.json).

### Pipeline (7 Phases)

| Phase | What happens | Model |
|-------|-------------|-------|
| 0 — Interview | Interactive Q&A to clarify the idea; human leaves after | GLM-5.2 |
| 1 — Spec | Autonomous spec generation (tech stack, features, acceptance criteria) | GLM-5.2 |
| 2 — Plan | Break spec into ordered, atomic issues with dependencies | GLM-5.2 |
| 3 — Execute | Autonomous loop: implement each issue with TDD, consult when stuck | Qwen 2.5 |
| 4 — Review | Code review across 5 axes; human-proxy approves | Qwen 2.5 + GLM-5.2 |
| 5 — Verify | Does it run locally? Fix if not | Qwen 2.5 |
| 6 — Done | Final git commit | — |
| 7 — Learn | Cross-issue pattern analysis; skill improvement | Qwen 2.5 |

### Knowledge Base (KB)

File-based JSON graph with progressive disclosure — agents load summaries first (cheap), drill into detail only when needed.

- **Per-project KB** (`factory/projects/<name>/kb/graph.json`): decisions, blockers, consultations, learnings for one project
- **Global KB** (`factory/kb/global-graph.json`): accumulated patterns across all projects

**Node types:** `intent`, `spec`, `issue`, `decision`, `blocker`, `consultation`, `proxy_decision`, `learning`

**Edge types:** `applied_to`, `caused_by`, `resolved_by`, `depends_on`, `parent_of`, `consulted_for`, `learned_from`

Schema defined in [`factory/kb/schema.json`](factory/kb/schema.json).

### Skills

**10 skills from [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)** (intact, unmodified):

`interview-me`, `spec-driven-development`, `planning-and-task-breakdown`, `incremental-implementation`, `test-driven-development`, `debugging-and-error-recovery`, `code-review-and-quality`, `code-simplification`, `git-workflow-and-versioning`, `using-agent-skills`

**5 custom factory skills:**

| Skill | What it does |
|-------|-------------|
| [`issue-executor`](factory/skills/issue-executor/SKILL.md) | Qwen's playbook for executing a single issue (TDD, stuck detection, KB logging) |
| [`consultant-protocol`](factory/skills/consultant-protocol/SKILL.md) | GLM's playbook for resolving doubts when Qwen gets stuck |
| [`human-proxy`](factory/skills/human-proxy/SKILL.md) | Replaces human approval using KB context (evaluates against original intent) |
| [`kb-manager`](factory/skills/kb-manager/SKILL.md) | Read/write/query the JSON KB graph with progressive disclosure |
| [`factory-learner`](factory/skills/factory-learner/SKILL.md) | Learns after each issue, improves factory skills immediately |

### Safety Features (inspired by [SantanderAI/ralph](https://github.com/SantanderAI/ralph))

| Feature | How it works |
|---------|-------------|
| `stop.md` | Any agent can create `stop.md` in the project dir to halt the pipeline cleanly |
| Regression suite | All previous tests re-run before each new issue |
| Thinking escalation | GLM-5.2 switches to `thinking=high` after 3 failures on an issue |
| Deep diagnosis | After 3 failures, GLM does a root-cause analysis instead of blindly retrying |
| Blocker logging | Stuck issues are logged to KB and skipped; pipeline continues |

### Self-Improvement Loop

After **every issue**, Qwen 2.5 analyzes what happened and learns:

```
Issue executed
  ↓
learn-issue.sh runs
  ├─ Did I get stuck? Why? → Add Red Flag to issue-executor skill
  ├─ Did GLM help? About what? → Could the skill cover this?
  ├─ Did proxy reject? Why? → Don't repeat that mistake
  ├─ What went well? → Log as best practice to global KB
  └─ Novel pattern? → Create new factory skill
  ↓
Skills improve. Next project is smarter.
```

---

## Installation

### Prerequisites

- [Ollama](https://ollama.ai) running locally
- [Pi](https://github.com/mariozechner/pi-coding-agent) coding agent (`npm install -g pi`)
- Models: `qwen2.5-coder:latest` and `glm-5.2:cloud` (or compatible)

```bash
# Install models
ollama pull qwen2.5-coder

# Install Pi
npm install -g pi

# Install skills from addyosmani
cd ~/Desktop/siesta
npx skills add addyosmani/agent-skills
```

### Setup

```bash
# Clone
git clone https://github.com/jairorodriguezarias/siesta.git ~/Desktop/siesta
cd ~/Desktop/siesta

# Make scripts executable
chmod +x factory/bin/siesta.sh factory/scripts/*.sh factory/hooks/*.sh

# Verify Ollama is running
ollama list

# Verify Pi is configured
pi --help
```

---

## Usage

```bash
cd ~/Desktop/siesta

# Give it an idea and answer the interview questions
./factory/bin/siesta.sh "Build a CLI pomodoro timer in Python"

# The agent will ask you questions to clarify what you want.
# Answer them. Then leave. 💤

# When you come back:
ls factory/projects/
# → pomodoro-timer-in-python/
#     ├── .git/          (full commit history)
#     ├── spec.md         (the spec GLM wrote)
#     ├── issues.md       (the issues GLM generated)
#     ├── src/            (the code Qwen wrote)
#     ├── tests/          (the tests)
#     └── kb/graph.json   (decisions, blockers, learnings)
```

### Emergency Stop

Create a `stop.md` file in the project directory to halt the pipeline:

```bash
echo "Something seems wrong, let me check" > factory/projects/my-project/stop.md
```

---

## Project Structure

```
siesta/
├── factory/
│   ├── bin/
│   │   └── siesta.sh              # Entry point
│   ├── scripts/
│   │   ├── run-pipeline.sh        # 7-phase pipeline orchestrator
│   │   ├── learn.sh               # Project-level learning
│   │   └── kb-manager.sh          # KB graph operations (query, append, link)
│   ├── hooks/
│   │   ├── pre-issue.sh           # Load KB context before issue
│   │   ├── post-issue.sh          # Log + git commit after issue
│   │   └── learn-issue.sh         # Per-issue micro-learning
│   ├── skills/                    # 5 custom factory skills
│   │   ├── issue-executor/SKILL.md
│   │   ├── consultant-protocol/SKILL.md
│   │   ├── human-proxy/SKILL.md
│   │   ├── kb-manager/SKILL.md
│   │   └── factory-learner/SKILL.md
│   ├── kb/
│   │   ├── global-graph.json      # Cross-project accumulated learnings
│   │   ├── graph.json             # Template KB
│   │   └── schema.json            # Node/edge type definitions
│   ├── config/
│   │   └── models.json            # Model routing config
│   └── projects/                  # Output: built projects land here
│
├── .agents/
│   ├── skills/                    # 10 addyosmani skills (intact)
│   ├── agents/
│   │   └── code-reviewer.md       # code-reviewer persona
│   ├── references/
│   │   ├── definition-of-done.md
│   │   └── security-checklist.md
│   └── hooks/
│       ├── pre-issue.sh
│       └── post-issue.sh
│
├── .pi/skills/                    # Symlinks for Pi agent
├── .claude/skills/                # Symlinks for Claude Code
├── AGENTS.md                      # Agent system documentation
└── .gitignore
```

---

## Acknowledgments

### [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)

> Production-grade engineering skills for AI coding agents.

Siesta uses 10 of the 24 skills from this repository (unmodified, intact). The skill anatomy, anti-rationalization tables, verification gates, and progressive disclosure patterns all come from Addy Osmani's work. The lifecycle (DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP) and the `definition-of-done.md` reference are directly from this project.

### [SantanderAI/ralph](https://github.com/SantanderAI/ralph)

> A configurable Bash/PowerShell loop that runs an AI coding CLI with a fresh session each iteration.

Siesta borrows several safety patterns from Ralph:

- **`stop.md`** signal — any agent can halt the pipeline cleanly
- **Regression suite** — re-run all previous tests before each new issue
- **Model escalation** — increase model thinking level after repeated failures
- **Deep diagnosis** — after 3 failures, trigger root-cause analysis instead of blindly retrying
- **Per-task learning** — improve skills after each task
- **Workspace continuity** — all state lives in files (KB + git), not in the session

---

## License

MIT — see [LICENSE](LICENSE).

## Author

Built with 💤 by [Jairo Rodriguez Arias](https://github.com/jairorodriguezarias)