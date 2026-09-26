# Siesta agent system

Siesta is a Python pipeline that invokes Pi with explicit models and skills.
It coordinates an interview, specification, issue plan, implementation,
review, verification, completion records and learning. Ollama provides model
access; the committed defaults use cloud models. See the
[README](README.md) for setup and the [local Ollama guide](docs/ollama-local.md)
for inference on your own machine.

## Roles and phases

| Phase | Role | Responsibility |
|---|---|---|
| 0: Interview | Planner | Clarify intent; finish with `INTENT_FINALIZED:` |
| 1: Specification | Planner | Write requirements and acceptance criteria |
| 2: Plan | Planner | Produce atomic issues headed `## Issue #N:` |
| 3: Execute | Worker | Implement and test each issue |
| 3: Consult / proxy | Consultant | Resolve doubts or evaluate approval requests |
| 4: Review | Worker + consultant | Review code, fix findings, obtain proxy approval |
| 5: Verify | Worker + Python checks | Run tests and applicable runtime checks |
| 6: Completion | Python | Record the real verdict and commit |
| 7: Learning | Consultant | Summarize patterns and propose skill updates |

Per-issue learning also runs during execution. The reviewer persona is defined
in [code-reviewer.md](.agents/agents/code-reviewer.md). These are roles within
the pipeline; their model names come from configuration.

The worker has file and shell tools during implementation, repair and review
fixes. Advisory calls receive their context in the prompt. The consultant,
proxy and learner must distinguish advice from actions actually executed.
Python owns verification gates, Git commits and KB bookkeeping.

## Issue execution and recovery

1. Load KB summaries and global principles with `pre_issue()`.
2. Check the existing regression suite. A failing suite gets one repair attempt.
   Commit a successful repair before starting the next issue; halt if it remains
   uncommitted. Two consecutive unrepairable suites halt execution.
3. Let the worker implement the issue, using TDD and the issue executor skill.
4. Resolve consultations or approval requests, with bounded retries.
5. Require a passing mechanical suite before `post_issue()` records completion.
6. Commit and run per-issue learning.

A worker requests advice using `CONSULT:`, `CONTEXT:` and `CODE:`.
The consultant provides a resolution and approach for a worker retry.
Two resolution-guided retries precede deep diagnosis; diagnosis can recommend
a fix, `SKIP:`, or `CRITICAL:` to create `stop.md` and halt.
There is no automatic web-search handler.

A worker requests approval with `PROXY_REQUEST:`. The consultant evaluates it
against the original intent, specification and recorded decisions. Only a
line-start `APPROVED` marker (optionally prefixed `PROXY_DECISION:`) authorizes
continuation. Rejections, revision requests and unmarked output receive feedback.

Tool-call narration, questions to an absent human and truncated output are
degenerate responses. They receive one feedback retry; continued degeneration
blocks the issue. Protocol examples inside code fences never count as signals.

Blocked work cannot become the next issue's base. Before restoring tracked files
and removing untracked product files, the pipeline saves binary patches and an
untracked-file archive under the generated project's `.git/siesta-recovery/`.
The KB and ignored evidence survive cleanup. Cleanup is limited to known failed
worker edits made during the active run. Unknown product edits at startup or an
issue boundary are preserved and block execution until committed, or explicitly
adopted with `--adopt-changes`. Workers cannot rewrite the issue plan.

## Review, verification and resume

- Review needs both `REVIEW_PASSED:` and explicit proxy approval. Fixes run
  with write tools, are committed, and receive a fresh review.
- Mechanical verification always reruns the suite, including after a model
  says `VERIFY_PASSED`. Red or absent tests fail verification; explicit model
  failure or a failed runtime smoke check also veto success.
- Python tests may live in `tests/` or at the project root. An empty pytest
  suite is skipped at the pre-issue gate and cannot prove issue completion.
- Verification persists `verify_verdict.txt`. Completion records and commits
  use this verdict; an unsuccessful result is recorded as `UNVERIFIED`.
- Resume uses committed issue completion nodes as its ledger. Pending issues invalidate
  downstream review and verification. Failed verification resumes at phase 5.
  Completed projects do not repeat completion commits or project learning.
- Completion records must commit successfully; rejected commits roll back the
  claim while preserving implementation edits. Altered local completion records
  block startup and cannot be adopted into the ledger automatically.
- Completed requirements are immutable, including acceptance code in fences.
  Legacy records are reconciled with their first committed plan; duplicate issue
  numbers are rejected. Use a new issue or `--iterate` for changed requirements.
- `.git/siesta-state.json` ties review and verification to product contents and
  executable modes. Changed products and missing fingerprints require fresh
  checks. Git hooks cannot silently alter a tested product during its commit.
- `--project` selects an existing Siesta Git root. `--iterate REQUEST` appends a
  specification amendment and unique issues; the latest identical request
  resumes. Rejected selection or local edits do not mutate project knowledge.
- `stop.md` is checked at issue boundaries. `SIESTA_PI_TIMEOUT` bounds every
  Pi call, including the interactive interview; timed-out process groups are
  killed and partial output is preserved.

## Model configuration and invocation

[`factory/config/models.json`](factory/config/models.json) maps `planner`,
`worker` and `consultant` to `model` and `provider`. The proxy and learner
use the consultant route. Models are selected manually at startup.

[`pipeline/pi.py`](factory/pipeline/pi.py) is the single invocation wrapper:

- Combine context and the closing directive into one positional prompt.
- Pass an explicit thinking level; unsupported model families use `off`.
- Parse stdout only. Provider stderr is stored after `PROVIDER_LOG:`.
- Failed calls return no answer. Saved provider logs and partial output are
  prefixed so their protocol markers cannot become authorization on resume.
- Bound calls with `SIESTA_PI_TIMEOUT` (seconds; default 1200).
- Warn when a loaded Ollama model serves less context than Pi declares.
  This advisory probe uses the default Pi catalog; custom profiles need the
  explicit served-context check in the local setup guide.

Verify native file and shell tool use through Ollama and Pi before choosing
a worker. Set Pi's `contextWindow` to the actual served window, not an assumed
catalog default. Local context is visible in `ollama ps` / `GET /api/ps`;
cloud models are proxied and need their model metadata checked separately.

`SIESTA_FACTORY` selects the directory containing configuration, factory skills,
KB and generated projects. Bundled skills are resolved from its parent
`.agents/skills/`. `PI_CODING_AGENT_DIR` selects an isolated Pi profile.
Repository paths and examples must remain portable; never hardcode user home
directories, credentials or machine-specific locations.

## Knowledge base

The KB is a JSON graph with `nodes` and `edges`. Newly appended node and edge
types are checked against an optional sibling [schema](factory/kb/schema.json).
Nodes contain an ID, type, summary,
detail and creation timestamp. Agents load summaries first and full detail
only when relevant.

| File | Scope |
|---|---|
| `factory/projects/<project>/kb/graph.json` | Project intent, decisions, blockers and learning |
| `factory/kb/global-graph.json` | Local cross-project memory; ignored by Git |
| [`factory/kb/global-seed.json`](factory/kb/global-seed.json) | Public standing principles for a new global KB |

A missing global graph is initialized from the sibling seed. An existing graph
is preserved, even when empty. Editing the seed affects fresh installations;
update an existing live graph explicitly when changing its principles.
Graph writes are atomic, but concurrent writers to the same graph are unsupported.

The six principles favor local applications, simplicity, readable code, Python,
English documentation and privacy. They enter specification prompts and every
issue's worker context. Generated application scope is separate from whether
the models themselves use local or cloud inference.

Run KB commands from a generated project with `PYTHONPATH` pointing to Siesta's
`factory/` directory:

```bash
python3 -m pipeline.kb query kb/graph.json --summary-only
python3 -m pipeline.kb query kb/graph.json --type decision --summary-only
python3 -m pipeline.kb get-node kb/graph.json NODE_ID
python3 -m pipeline.kb append-node kb/graph.json decision 'Summary' 'Full detail'
python3 -m pipeline.kb append-edge kb/graph.json FROM_ID TO_ID applied_to
```

## Skills and development

Pi receives each skill through an explicit `--skill` path. The repository
contains ten adapted skills under `.agents/skills/` and five factory skills
under `factory/skills/`. No separate installation or runtime view is needed.

The learner may update or create factory skills only. It cannot modify the
adapted skills; those require a repository change. Python applies supported
learning blocks after fence-aware parsing. A new skill proposal is a KB record
unless it supplies the complete content required for a file update.

Git workflow and skill discovery are for interactive repository development;
the pipeline implements those operations directly in Python. Follow the
[Definition of Done](.agents/references/definition-of-done.md), use meaningful
tests for behavior changes, and review code before merging. Keep documentation,
model routing and actual skill attachments aligned. Preserve license notices.

| Source | Purpose |
|---|---|
| [`factory/bin/siesta.sh`](factory/bin/siesta.sh) | Shell entry point and local console log |
| [`pipeline/__main__.py`](factory/pipeline/__main__.py) | Dispatch, checkpoints, completion and failure records |
| [`pipeline/phases.py`](factory/pipeline/phases.py) | Prompts, execution, recovery and verification |
| [`pipeline/pi.py`](factory/pipeline/pi.py) | Model calls, thinking, timeouts and context probe |
| [`pipeline/repository.py`](factory/pipeline/repository.py) | Strict commits, completion ledger and product fingerprints |
| [`pipeline/iterations.py`](factory/pipeline/iterations.py) | Additional requests, specification amendments and issue plans |
| [`pipeline/files.py`](factory/pipeline/files.py) | Git-aware filtering of private, ignored and dependency prompt inputs |
| [`pipeline/text.py`](factory/pipeline/text.py) | Protocol markers and parsers |
| [`pipeline/kb.py`](factory/pipeline/kb.py) | Graph storage and CLI |
| [`pipeline/learn.py`](factory/pipeline/learn.py) | Per-issue and project learning |
| [`factory/tests/`](factory/tests/) | Unit, real-Git and fake-Pi integration tests |

See [testing.md](docs/testing.md) for validation commands and limitations.
