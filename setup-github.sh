#!/bin/bash
# Fix shell and setup GitHub repo for Siesta
cd ~/Desktop/siesta

# Fix any remaining SLDC references
for f in factory/bin/siesta.sh; do
  sed -i '' 's|/Desktop/SLDC/|/Desktop/siesta/|g' "$f" 2>/dev/null
  sed -i '' 's|/SLDC/|/siesta/|g' "$f" 2>/dev/null
done

chmod +x factory/bin/siesta.sh

# Remove skills-lock.json if exists
rm -f skills-lock.json

# Create .gitignore
cat > .gitignore << 'EOF'
# macOS
.DS_Store
*/.DS_Store

# Node
node_modules/

# Python
__pycache__/
*.pyc
.venv/
venv/

# Project outputs (each project has its own git repo)
factory/projects/

# KB global graph (accumulated learnings, not code)
# factory/kb/global-graph.json

# Logs
*.log
EOF

# Create README.md
cat > README.md << 'READMEEOF'
# 💤 Siesta

**"Give me an idea, go take a siesta, come back to working code."**

Siesta is a local-first autonomous development pipeline for your Mac. You give it a project idea, answer a few questions, then walk away. When you come back, there's a git repo with working, tested code that runs locally.

No cloud APIs. No external services. Everything runs on your machine using [Ollama](https://ollama.ai) local models.

---

## How It Works

```
You:  "Build me a CLI pomodoro timer in Python"
      ↓
Phase 0: GLM-5.2 interviews you about what you want
         You answer. You leave. 💤
      ↓
Phase 1: GLM-5.2 writes the spec autonomously
Phase 2: GLM-5.2 breaks it into issues
Phase 3: Qwen 2.5 Coder executes each issue:
         ├─ Writes code + tests
         ├─ Stuck? → GLM-5.2 consults (thinking escalates after 3 fails)
         ├─ 3 fails? → Deep diagnosis (like Ralph's "juez desatascar")
         ├─ Need approval? → Human-proxy (GLM-5.2) decides based on KB
         ├─ Regression suite runs before each issue
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

### Pipeline

```
Phase 0: HUMAN INTERACTIVE → interview → INTENT_FINALIZED → human leaves
Phase 1: SPEC → GLM-5.2 → spec.md
Phase 2: PLAN → GLM-5.2 → issues.md
Phase 3: EXECUTE → Qwen 2.5 (autonomous loop per issue)
Phase 4: REVIEW → Qwen 2.5 + code-reviewer persona + human-proxy
Phase 5: VERIFY → Qwen 2.5 → does it run locally?
Phase 6: DONE → git commit
Phase 7: LEARN → Qwen 2.5 learns from KB, improves skills
```

### Knowledge Base (KB)

File-based JSON graph with progressive disclosure:

- **Per-project KB** (`projects/<name>/kb/graph.json`): decisions, blockers, consultations, learnings
- **Global KB** (`factory/kb/global-graph.json`): accumulated patterns across all projects

Node types: `intent`, `spec`, `issue`, `decision`, `blocker`, `consultation`, `proxy_decision`, `learning`

Progressive disclosure: agents query summaries first (cheap), drill into detail only when needed.

### Skills

**10 skills from [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)** (intact, unmodified):

`interview-me`, `spec-driven-development`, `planning-and-task-breakdown`, `incremental-implementation`, `test-driven-development`, `debugging-and-error-recovery`, `code-review-and-quality`, `code-simplification`, `git-workflow-and-versioning`, `using-agent-skills`

**5 custom factory skills:**

| Skill | What it does |
|-------|-------------|
| `issue-executor` | Qwen's playbook for executing a single issue |
| `consultant-protocol` | GLM's playbook for resolving doubts |
| `human-proxy` | Replaces human approval using KB context |
| `kb-manager` | Read/write/query the JSON KB graph |
| `factory-learner` | Learns after each issue, improves skills |

### Safety Features (inspired by [SantanderAI/ralph](https://github.com/SantanderAI/ralph))

| Feature | How it works |
|---------|-------------|
| `stop.md` | Any agent can create `stop.md` to halt the pipeline cleanly |
| Regression suite | All previous tests re-run before each new issue |
| Thinking escalation | GLM-5.2 switches to `thinking=high` after 3 failures |
| Deep diagnosis | After 3 failures, GLM does a root-cause analysis (like Ralph's `juez desatascar`) |
| Blocker logging | Stuck issues are logged to KB and skipped, pipeline continues |

### Self-Improvement Loop

After **every issue**, Qwen 2.5 analyzes what happened and learns:

```
Issue executed
  ↓
learn_issue() runs
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
- [Pi](https://github.com/mariozechner/pi-coding-agent/) coding agent (`npm install -g pi`)
- Models: `qwen2.5-coder:latest` and `glm-5.2:cloud` (or compatible)

```bash
# Install models
ollama pull qwen2.5-coder
# GLM-5.2 via Ollama cloud provider

# Install Pi
npm install -g pi

# Install skills from addyosmani
cd ~/Desktop/siesta
npx skills add addyosmani/agent-skills
```

### Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/siesta.git ~/Desktop/siesta
cd ~/Desktop/siesta

# Make executable
chmod +x factory/bin/siesta.sh

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
│   │   └── siesta.sh              # 💤 Entry point
│   ├── pipeline/                  # Python orchestrator (python3 -m pipeline)
│   │   ├── __main__.py            # Checkpoint, failure trap, dispatch, summary
│   │   ├── phases.py              # Phase bodies 0-7
│   │   ├── learn.py               # Per-issue + project learning
│   │   ├── pi.py                  # run_pi() model-call wrapper
│   │   ├── kb.py                  # KB graph store + CLI shim
│   │   └── text.py                # Marker regexes + parsers
│   ├── tests/                     # Unit + fake-pi integration tests
│   ├── skills/                    # 5 custom factory skills
│   │   ├── issue-executor/
│   │   ├── consultant-protocol/
│   │   ├── human-proxy/
│   │   ├── kb-manager/
│   │   └── factory-learner/
│   ├── kb/
│   │   ├── graph.json             # Template KB
│   │   ├── global-graph.json      # Cross-project accumulated learnings
│   │   └── schema.json           # Node/edge type definitions
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
└── .gitignore
```

---

## Acknowledgments

Siesta builds on ideas from two excellent open-source projects:

### [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)

> Production-grade engineering skills for AI coding agents.

Siesta uses 10 of the 24 skills from this repository (unmodified, intact). The skill anatomy, anti-rationalization tables, verification gates, and progressive disclosure patterns all come from Addy Osmani's work. The lifecycle (DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP) and the `definition-of-done.md` reference are directly from this project.

### [SantanderAI/ralph](https://github.com/SantanderAI/ralph)

> A configurable Bash/PowerShell loop that runs an AI coding CLI with a fresh session each iteration.

Siesta borrows several safety patterns from Ralph:

- **`stop.md`** signal — any agent can halt the pipeline cleanly
- **Regression suite** — re-run all previous tests before each new issue (Ralph's "suite de evidencias persistente")
- **Model escalation** — increase model thinking level after repeated failures (Ralph's `RALPH_MODEL_CAPABILITY` escalation)
- **Deep diagnosis** — after 3 failures, trigger a root-cause analysis instead of blindly retrying (Ralph's `[juez desatascar]`)
- **Per-task learning** — improve skills after each task (Ralph's `maestro` skill)
- **Workspace continuity** — all state lives in files (KB + git), not in the session

The `juez` (independent reviewer) and `maestro` (skill curator) concepts from Ralph directly inspired Siesta's `human-proxy` and `factory-learner` skills.

---

## License

MIT

## Author

Built with 💤 by [Jairo Rodriguez Arias]
READMEEOF

echo "✓ README.md created"
echo "✓ .gitignore created"

# Create LICENSE
cat > LICENSE << 'LICENSEEOF'
MIT License

Copyright (c) 2026 Jairo Rodriguez Arias

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
LICENSEEOF

echo "✓ LICENSE created"

# Git init and commit
cd ~/Desktop/siesta
rm -rf .git  # Clean any existing git
git init
git add -A
git commit -m "💤 Initial commit: Siesta — autonomous local dev pipeline

- 7-phase pipeline: interview → spec → plan → execute → review → verify → learn
- Dual model: GLM-5.2 (planner/consultant) + Qwen 2.5 Coder (worker/learner)
- KB graph with progressive disclosure (JSON, file-based)
- Human-proxy agent replaces human approval in autonomous phases
- Per-issue learning loop (self-improving skills)
- Safety: stop.md, regression suite, thinking escalation, deep diagnosis
- 10 addyosmani skills + 5 custom factory skills
- Inspired by addyosmani/agent-skills and SantanderAI/ralph"

echo ""
echo "✓ Git commit done"
echo ""
git log --oneline
echo ""
echo "=== Final structure ==="
find . -not -path './.git/*' -not -name '.DS_Store' -type f | sort