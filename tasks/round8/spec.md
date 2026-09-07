# Spec: Round-8 — Honest context for the local worker

## Objective

The pomodoro validation run (2026-09-06) exposed a silent truncation failure:
pi's catalog declares gemma4 with a 131072-token context window, but Ollama
serves it at 8192. pi therefore never compacts, long worker prompts overflow
the real window, `--context-shift` silently discards the head (where skills
and the closing directive live), and the model keeps doing tool work but
never emits the final protocol text — stdout comes back empty, the degenerate
guard blocks the issue. Issues #3 and #4 died exactly this way with real
code left uncommitted in the tree.

The decision: **gemma4 stays at its real 8K served context** (no bump). The
improvement is honesty, not size:

1. Fix pi's user catalog so it states the truth (8192) and pi compacts
   worker context to fit the real window.
2. Add a pipeline startup guard that detects the mismatch automatically:
   read Ollama's actually-served context (`ollama ps`) and compare it with
   pi's declared catalog window for every routed model. Warn loudly when
   the served context is smaller than what pi believes.

Success: catalog truthful, guard in place with tests, docs in sync, full
suite green, everything pushed.

## Tech Stack

Python 3.10+ (stdlib only), `unittest` via `python3 -m unittest discover -s
tests`, fake-pi stub on PATH for integration scenarios. `ollama ps` CLI (or
its `/api/ps` equivalent) for the served-context probe. No new dependencies.

## Commands

```
Test:   cd factory && python3 -m unittest discover -s tests
Commit: git add <paths> && git commit  (one commit per issue)
```

## Project Structure

```
factory/pipeline/pi.py        → _served_context() probe + warn_if_context_mismatch()
factory/pipeline/__main__.py  → startup call site (before phase 0)
factory/tests/test_pi.py       → unit tests (parse + mismatch cases)
factory/tests/test_pipeline.py → integration: startup emits the warn
~/.pi/agent/models.json        → NOT repo code: fixed in place (8192)
AGENTS.md                      → guard list + worker-registration note updated
tasks/round8/                  → this spec + issues.md
```

## Code Style

Match the file you are editing. House rules already in force:
- Guard first, log honest (warn, never silent).
- No new abstractions for one-time reads; a small helper in pi.py is fine.
- Comments explain *why* (the mismatch incident), never narrate *what*.
- Every issue: test first (red), fix (green), full suite green, commit.

## Boundaries

- **Do not** change the model, the provider, or the served context size.
- **Do not** bump `OLLAMA_CONTEXT_LENGTH` or edit Modelfiles — 8K stays.
- **Do not** touch the pomodoro run in `factory/projects/build-a-pomodoro-app-*`
  while it is live; its analysis happens after close-out.
- ~/.pi/agent/models.json is user config outside the repo — fix it in place,
  document it in AGENTS.md, do not track it in git.
- The guard is advisory (warn), not a halting gate: a mismatch must never
  prevent a run from starting (the user may fix the catalog later).

## Success Criteria

1. `~/.pi/agent/models.json` states `contextWindow: 8192` for gemma4.
2. `python3 -m pipeline --auto "<idea>"` emits a clear `[warn]` at startup
   whenever a routed Ollama model's served context < pi's declared window.
3. The warn is silent when served >= declared (normal case, e.g. GLM cloud
   or a correctly registered model).
4. Unit tests cover: JSON parse of `ollama ps`, served < declared → warn,
   served >= declared → no warn, ollama absent/unreadable → silent skip
   (advisory guard must never crash the run).
5. Integration test proves the startup path calls the guard.
6. Full suite green: `cd factory && python3 -m unittest discover -s tests`.
7. AGENTS.md documents the guard and the true-window registration rule.
8. Round-8 findings from the pomodoro run recorded in `factory/BACKLOG.md`.