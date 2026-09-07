# Issues: Round-8 — Honest context for the local worker

## Issue #1: Served-context probe + mismatch warn (pi.py)

Description:
Add `_served_context(model: str) -> int | None` to `factory/pipeline/pi.py`:
run `ollama ps --format json`, find the loaded model matching the routed
model name (substring match on name, e.g. "gemma4:latest" in "gemma4:latest"),
return its `context_length` (int) or None when Ollama is absent, unreadable,
or the model is not loaded. None means "cannot verify" and must NOT warn —
the guard is advisory.

Add `warn_if_context_mismatch(model: str, declared: int) -> bool` in the
same file: probe the served context; when probe returns an int and it is
strictly smaller than the declared window, emit one `warn(...)` line naming
model, served, declared, and the consequence ("pi compacts to its catalog
window; the real one is smaller — long worker prompts will be silently
truncated, tool work may lose the closing directive"). Return True when a
warn was emitted.

Declared windows come from pi's user catalog `~/.pi/agent/models.json` —
add `_declared_context(model: str) -> int | None` reading that file (models
may be unregistered → None → no warn).

Acceptance criteria:
- Three helpers exist in pi.py with the exact contracts above.
- `warn_if_context_mismatch` returns False and stays silent when probe is
  None or declared is None.
- Unit tests with a stubbed `ollama` binary / stubbed subprocess result
  cover: happy parse, served < declared → warn + True, served >= declared →
  silent + False, unreadable JSON → None → silent, catalog unreadable →
  None → silent.

Dependencies: none.

## Issue #2: Startup guard call (pipeline __main__)

Description:
Call the guard at pipeline startup in `factory/pipeline/__main__.py`
`_run()`, before phase 0, once per routed role model (planner, worker,
consultant — dedupe repeated models). Pull the declared window via
`pi._declared_context`, call `pi.warn_if_context_mismatch(model, declared)`.
The guard must never crash the run: wrap in a bare `try/except Exception`
that logs nothing on failure (advisory-only).

Acceptance criteria:
- `_run()` invokes the guard before phase 0 for each distinct routed model.
- Integration test (fake pipeline run) shows the `[warn]` line at startup
  when the stub serves a smaller context than the catalog declares.
- A broken probe (ollama absent) does not prevent the pipeline from
  starting (existing integration tests keep passing).
- Full suite green.

Dependencies: Issue #1.

## Issue #3: Truthful catalog + docs in sync

Description:
Fix `~/.pi/agent/models.json` in place: gemma4 `contextWindow` 131072 →
8192 (the real served context — pi compacts worker context to fit). GLM's
cloud entry stays as is. Then sync docs:

- AGENTS.md "Model Routing" section: document the incident-driven rule —
  a worker must be registered with its **true served** context window, the
  `ollama ps` CONTEXT column is the source of truth, and the new startup
  guard warns on mismatch.
- AGENTS.md guard list ("Guards around the loop"): add the context-mismatch
  warn as an advisory guard.
- `factory/BACKLOG.md`: add the round-8 findings section from the pomodoro
  run (guard judges text not artifacts; blocked-issue residue uncommitted;
  root tests invisible to regression gate) with this round's commits.

Acceptance criteria:
- `~/.pi/agent/models.json` shows `contextWindow: 8192` for gemma4.
- AGENTS.md mentions the true-context registration rule and the guard.
- BACKLOG.md carries the round-8 findings with commit hashes.
- `python3 -m pipeline --auto "smoke"` no longer warns for gemma4 (catalog
  now truthful) — verified manually after the catalog fix.
- Full suite green.

Dependencies: Issues #1, #2.