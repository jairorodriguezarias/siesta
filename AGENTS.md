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
| 2b: Design review | Three specialists | Independently check comprehension, simplicity and implementation readiness |
| 3: Execute | Worker | Implement and test each issue |
| 3: Consult / proxy | Consultant | Resolve doubts or evaluate approval requests |
| 4: Review | Integration + quality reviewers, worker, proxy | Independently review code, fix findings, obtain proxy approval |
| 5: Verify | Worker + Python checks | Run tests and applicable runtime checks |
| 5: Requirement evidence | Consultant + Python | Map acceptance criteria to passing test IDs and source; flag drift |
| 6: Completion | Python | Record the real verdict and commit |
| 7: Learning | Consultant | Summarize patterns and propose skill updates |

Per-issue learning also runs during execution. Agent identities and tool
permissions are defined in `factory/pipeline/agents.py` with required Markdown
definitions in `factory/agents/`. Their model names come from project routing.

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
5. Require a passing mechanical suite and independent issue review before
   `post_issue()` records completion.
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
The KB and ignored evidence survive cleanup. Unknown dirty work found when
resuming is preserved; the user must commit or reconcile it before continuation.
Workers and review fixes cannot rewrite either `spec.md` or `issues.md`.

## Review, verification and resume

- Specs define acceptance bullets `- R1: ...` with unique IDs; legacy acceptance
  bullets receive stable IDs in document order. Design review uses three fresh,
  tool-free calls with no KB or authoring conversation. Approval is bound to
  the exact intent, specification, plan and consultant routing.
- Isolated calls disable context-file, skill, extension and prompt-template
  discovery, project approval and session persistence. Explicit system/append
  prompts also suppress implicit `SYSTEM.md` and `APPEND_SYSTEM.md` loading.
- Final review needs passing integration and quality reports plus explicit proxy
  approval. Fixes run with write tools, are committed, and receive a fresh review.
- Review policy is pinned per project: normal allows three rounds, two repairs,
  20 calls and 60 active minutes; deep allows five rounds, two repairs, two
  consecutive clean rounds, 40 calls and 120 active minutes. Retries, repairs,
  proxy decisions and adjudications spend the same persisted budget.
- Mechanical verification always reruns the suite, including after a model
  says `VERIFY_PASSED`. Red or absent tests fail verification; explicit model
  failure or a failed runtime smoke check also veto success.
- Python tests may live in `tests/` or at the project root. An empty pytest
  suite is skipped at the pre-issue gate and cannot prove issue completion.
- Verification persists `verify_verdict.txt`. Completion records and commits
  use this verdict; an unsuccessful result is recorded as `UNVERIFIED`.
- `.siesta/requirements.md` maps each criterion to actual passing Python test
  IDs and existing source paths. Missing evidence or documentation drift vetoes
  completion. Semantic coverage is a model judgment, not a mechanical proof.
- `.siesta/` is ignored evidence and never enters source prompts. Call records
  measure duration and exit status; unavailable token/cost totals stay null.
- Resume uses issue completion nodes as its ledger. Pending issues invalidate
  downstream review and verification. Failed verification resumes at phase 5.
  Completed projects do not repeat completion commits or project learning.
- Active legacy projects lacking issue review evidence revalidate completed
  issues before new implementation. `.siesta/migration.json` records pinned
  configuration and review progress without duplicating completion nodes.
- `stop.md` is checked at issue boundaries. `SIESTA_PI_TIMEOUT` bounds every
  Pi call; timed-out calls are treated as no answer and partial output is
  preserved.

`--project PATH` selects an existing Siesta Git root using its committed intent.
`--iterate REQUEST` appends new requirements and issues without rewriting
completed issue bodies. Repeating the latest request resumes its work; a new
request requires completing the current one. Amendments use distinct acceptance
IDs and pass the same independent design review and evidence audit.
`--adopt-changes` explicitly commits local edits after ledger validation.
Invalid project selection and rejected dirty work do not mutate the project KB.

## Model configuration and invocation

[`factory/config/models.json`](factory/config/models.json) maps `planner`,
`worker` and `consultant` to default `model` and `provider` routes. CLI and
desktop selections can override routes by phase and agent; saved project
selections take precedence on resume. The desktop catalog combines the active
Pi profile with Ollama's installed tags and offers an explicit compatibility
check. An unprepared model is never silently substituted.

[`pipeline/pi.py`](factory/pipeline/pi.py) is the single invocation wrapper:

- Combine context and the closing directive into one positional prompt.
- Pass an explicit thinking level; unsupported model families use `off`.
- Parse stdout only. Provider stderr is stored after `PROVIDER_LOG:`.
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

Tool-enabled calls register skills through explicit `--skill` paths for Pi to
load on demand. Tool-free calls additionally receive each selected `SKILL.md`
in the prompt: registration alone does not expose its content without a reader
tool. Missing required files fail before invocation. Isolated design/evidence
reviewers receive no skills. The repository contains ten adapted skills under
`.agents/skills/` and five factory skills under `factory/skills/`. No separate
installation or runtime view is needed. See [skills and context](docs/skills-and-context.md).

The learner may propose updates or new factory skills only. It cannot modify
the adapted skills; those require a repository change. Python parses supported
learning blocks with fence awareness and records complete replacement proposals
in the KB. An independent `skill-reviewer` compares candidate, previous version
and evidence; scenario tests, including real model behavior, must pass before
atomic activation for future projects. Current projects retain pinned skills.

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
| [`pipeline/web/`](factory/pipeline/web/) | Local retro desktop, serialized CLI process adapter and Snake |
| [`pipeline/events.py`](factory/pipeline/events.py) | Optional atomic status channel for desktop phases and interview input |
| [`pipeline/iterations.py`](factory/pipeline/iterations.py) | Additional requests, immutable prior issues and specification amendments |
| [`pipeline/design.py`](factory/pipeline/design.py) | Isolated design review and requirement evidence |
| [`pipeline/repository.py`](factory/pipeline/repository.py) | Committed ledger, product identity and Git state |
| [`pipeline/files.py`](factory/pipeline/files.py) | Source selection and local evidence directory |
| [`pipeline/evaluate.py`](factory/pipeline/evaluate.py) | Live model evaluations with independent CLI checks |
| [`pipeline/text.py`](factory/pipeline/text.py) | Protocol markers and parsers |
| [`pipeline/kb.py`](factory/pipeline/kb.py) | Graph storage and CLI |
| [`pipeline/learn.py`](factory/pipeline/learn.py) | Per-issue and project learning |
| [`pipeline/skill_activation.py`](factory/pipeline/skill_activation.py) | Independent skill validation and activation |
| [`pipeline/model_catalog.py`](factory/pipeline/model_catalog.py) | Pi/Ollama model discovery and compatibility checks |
| [`pipeline/migration.py`](factory/pipeline/migration.py) | Legacy project evidence and revalidation |
| [`factory/tests/`](factory/tests/) | Unit, real-Git and fake-Pi integration tests |

See [testing.md](docs/testing.md) for validation commands and limitations.
