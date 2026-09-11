# Testing Siesta

Run from the repository root with the Python environment described in the
[README](../README.md#installation) active:

```bash
cd factory
python -B -m unittest discover -s tests -v
```

The suite uses temporary directories and a fake Pi executable; it does not
need model credentials or a running Ollama server. Pytest is required because
integration tests exercise generated projects with real test subprocesses.

## What the suite covers

- Protocol parsing, fenced examples and malformed model output.
- KB updates, seeded initialization and preservation of local knowledge.
- Planner retries, worker escalation, proxy approval and review fixes.
- Mechanical test gates, runtime smoke checks and persisted verdicts.
- Real Git commits, failed commit hooks, recovery archives and residue cleanup.
- Checkpoints, issue idempotency, incomplete resumes and completed reruns.
- Model routing, tool permissions, timeouts and context warnings.

A passing factory suite validates the orchestrator against those scenarios.
It does not establish that a particular model can finish arbitrary projects.

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
