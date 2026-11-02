# Skills and context

Siesta uses Markdown skills as model instructions. Python selects them for each
phase and owns execution gates, recovery, completion records and Git commits.
Following a skill is model behavior; passing the test gate is observed evidence.

## Instruction delivery

`pipeline.pi.build_args()` registers the selected skills through explicit
`--skill` paths. With file tools available, Pi advertises their metadata and the
worker reads the full files on demand. Registration is not evidence that a model
actually read or followed a skill.

Every Pi call also resolves an explicit agent identity from
`factory/pipeline/agents.py` and loads its required Markdown definition from
`factory/agents/`. The definition is included in the prompt, including for
isolated, text-only calls. The Python registry controls the model role, admitted
context categories, output contract and maximum tool allowlist; Markdown text
cannot grant tools. The planner and consultant have no tools, while the worker
receives the registered project tools. Callers may narrow a tool list, and a
request outside the agent's allowlist fails before Pi runs.

For calls with `tools="no"`, Siesta also reads each selected `SKILL.md` and
prepends its complete content to the prompt. Missing files fail before Pi runs.
The phase-specific task and output contract follow the skills and take
precedence over their generic workflows. Advisory roles must distinguish
analysis and recommendations from actions actually executed. A referenced file
is not automatically included; tool-free contracts state the needed rules
directly and require missing evidence to be reported.

The final directive stays last. Prompts larger than 64,000 UTF-8 bytes travel
through Pi's stdin support to avoid operating-system argument limits. This is a
transport threshold, not a model context budget or permission to truncate data.

## Context by role

| Role | Supplied context | Tools and limits |
| --- | --- | --- |
| Planner | Idea/transcript, intent, requirements or plan for the current phase | No tools; Python reads human answers and confirmation and saves returned documents. |
| Worker | Issue, project KB summaries, global principles and selected source | Registered file/shell tools; leaves product changes uncommitted. |
| Consultant | Question, attempts, relevant supplied code and KB summaries | No tools; recommends checks when evidence is insufficient. |
| Approval proxy | Full intent and decision records, current specification, request or review | Consultant identity with no tools; missing evidence requires revision. |
| Review and verification | Selected source and phase evidence | No tools; review fixes get a separate tool-enabled worker call. Python runs actual checks. |
| Learner | Outcomes, consultation/retry evidence and KB summaries | Consultant identity with no tools; returns actions/proposals for Python to persist. |

Normal issue execution routes `CONSULT:` and `PROXY_REQUEST:` through bounded
retries. Regression repairs and review fixes have a single attempt without an
advisory loop. Those markers block such an attempt rather than implying an
approval or a successful repair.

## Persistent memory and limits

The project graph (`kb/graph.json`) stores summaries and full details. Before an
issue, Python supplies all project summaries and the global principles; a worker
can use the KB CLI to retrieve a specific node's detail. This is explicit lookup,
not semantic retrieval. Project summaries currently have no relevance ranking or
shared token budget.

`gather()` includes up to 500 lines per source file and about 120,000 characters
in total, marking truncation. It excludes ignored files, dependency trees and
selected private paths. This filters prompt content; it does not sandbox a
worker's file tools. Skills, documents, KB records and tool results consume
additional context. Pi's declared context window must match the model's actual
served capacity; the advisory Ollama probe does not guarantee that every prompt
fits, especially with custom profiles or cloud routes.

## Independent review

Design comprehension/readiness and requirement-evidence audits use fresh
tool-free Pi calls. They disable sessions, implicit context files, extensions,
skills and prompt templates, and supply explicit system prompts. Design readers
receive intent, specification and plan; requirement readers receive criteria,
passing test IDs and selected source. They do not receive author conversation or
KB history. `isolated=True` rejects explicit skills too.

This separation follows the principle behind Google's
[Elephant–Goldfish Model](https://github.com/google/elephant-goldfish-model):
context-rich authorship followed by independent readers. Siesta's two review
lenses are its own implementation, not the complete upstream EGM workflow.
Fresh conversation context is not filesystem isolation, and a model's semantic
coverage judgment is not a mechanical proof.

## Learning and skill changes

Only factory skills may be updated by the learner. An improvement proposal is a
KB decision, not an applied file change. Replacing an existing skill requires its
complete current text in the supplied context; a directory name is insufficient.
Otherwise the learner must return a proposal only.

Actual updates use unindented `SKILL_UPDATE_START: name` and `SKILL_UPDATE_END`
outer markers. Literal marker examples inside a replacement must be indented or
fenced. Python preserves replacement Markdown, ignores quoted outer blocks,
discards unfinished replacements and never executes their contents as KB actions.
Destination/content checks do not prove the semantic quality of a learned rule.

The ten adapted skills are repository-maintained. The discovery map also mentions
optional upstream workflows, which must not be treated as installed dependencies.
Use the current inventory and available tools. See [testing](testing.md) for
offline verification and its limits.
