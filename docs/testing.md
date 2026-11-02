# Testing Siesta

Run from the repository root with the Python environment described in the
[setup guide](getting-started.md) active:

```bash
cd factory
python -B -m unittest discover -s tests -v
```

The suite uses temporary directories and a fake Pi executable; it does not
need model credentials or a running Ollama server. Pytest is required because
integration tests exercise generated projects with real test subprocesses.

The [desktop guide](desktop.md#verification) adds the Node Snake-rule tests and
an optional Playwright check using a controlled local child process. Neither
requires live model access. Backend HTTP/process tests run in the normal suite.

## What the suite covers

- Protocol parsing, fenced examples and malformed model output.
- KB updates, seeded initialization and preservation of local knowledge.
- Planner retries, worker escalation, proxy approval and review fixes.
- Mechanical test gates, runtime smoke checks and persisted verdicts.
- Real Git commits, failed commit hooks, recovery archives and residue cleanup.
- Checkpoints, issue idempotency, incomplete resumes and completed reruns.
- Model routing, tool permissions, timeouts and context warnings.
- Full skill delivery to tool-free calls, large-prompt transport, complete proxy
  decision evidence, and skill replacement examples isolated from KB actions.
- Isolated design review, malformed replies, changed requirements and cached approvals.
- Requirement mappings to actual passing pytest IDs, including parametrized IDs.
- Product changes during verification, failed completion commits and legacy resume gates.
- Existing-project selection, explicit adoption, append-only iterations, repeated
  requests, immutable prior issues and evidence for old and new requirement IDs.

When Pi and Node are installed, the native isolation test also exercises Pi's
actual argument parser and resource loader with temporary sentinel files. It
checks global/project system-prompt inheritance and confirms that a tool-free
call's skill body survives native argument parsing even though Pi omits its
skill catalog. These checks need no model calls or account credentials. They
skip when Pi is unavailable, as in offline CI.

A passing factory suite validates the orchestrator against those scenarios.
It does not establish that a particular model can finish arbitrary projects.

## Reproducible live evaluations

With Pi, Ollama access, Git identity and pytest configured, run from the root:

```bash
PYTHONPATH=factory python -B -m pipeline.evaluate \
  --output .runtime/evaluation-1 --case sum --case slug --timeout 600
```

Choose a new output directory for each run. The evaluator copies the pipeline,
configuration, factory skills and adapted skills into an isolated factory for
each case. Learning cannot modify the working repository's skills or KB.

The two cases exercise a sum CLI and a slug CLI. Their fixed input/output checks
are maintained outside the generated project, independently of model-written
tests. A passing result requires all external checks, a `VERIFY_PASSED` verdict,
a complete checkpoint and a relaunch with no additional model calls or commits.

`results.json` records model routes, elapsed time, call count, independent
checks, resume behavior and a hash of the tested pipeline sources. Console
logs and projects remain beside it. The harness is noninteractive, so its
human-intervention count is zero. Timeouts fail the case and stop its processes.

Token counts and monetary cost are **unknown**, not zero: Pi's text mode does
not expose those totals. Model-call duration is not provider billing latency.
These tiny cases establish observed behavior only, not a general success rate.
See [the recorded evaluation](evaluations/2026-11-02.md).

The final requirement gate currently needs pytest IDs. Non-Python runners can
still supply mechanical results but cannot establish requirement coverage.
Legacy acceptance lists are numbered in order; absent acceptance criteria must
be added explicitly before an active legacy project can continue.

## Validate a model profile

Follow the [local Ollama guide](ollama-local.md) to confirm served context and
native Pi tool execution. Then run a small project with explicit acceptance
criteria and tests required in every issue.

Inspect the generated project rather than relying only on the final message:

1. Confirm the printed role assignments match the intended profile.
2. Check actual file edits and successful tool events.
3. Run the generated tests independently.
4. Exercise the application and check its expected output.
5. Require a passing verification verdict, no pending issues and a
   `complete` checkpoint.
6. Relaunch the same idea and confirm that completed work is not repeated.

A process remaining alive is limited evidence. A GUI requires visual and
interaction checks; a command-line program needs meaningful inputs and output
assertions. Automated smoke detection covers supported layouts, not every
possible application.

Keep transcripts, project KBs and run artifacts local. Share only selected,
reviewed evidence that contains no credentials or private project information.
