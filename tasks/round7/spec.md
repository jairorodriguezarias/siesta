# Spec: Round-7 — Close out the open pipeline backlog

## Objective

Execute every open BACKLOG item that can be fixed with code (no live model
runs), one at a time, TDD per item, progressive disclosure. The remaining
open items after round-6 are: #34, #35, #38, #39, #41, #42, plus the two
"Related hardening ideas" (stderr noise in parsed text; markers inside
fenced code blocks). #8 and #25 stay pending — they close only with live
e2e runs (pomodoro relaunch), which is a separate decision.

Success: every item marked ✅ in `factory/BACKLOG.md` with its commit,
full suite green, AGENTS.md guard list in sync, honest summary at the end.

## Tech Stack

Python 3.10+ (stdlib only — `int | None` syntax already in use), `unittest`
via `python3 -m unittest discover -s tests`, fake-pi stub on PATH for
integration scenarios. No new dependencies.

## Commands

```
Test:   cd factory && python3 -m unittest discover -s tests
Commit: git add <paths> && git commit  (one commit per issue)
```

## Project Structure

```
factory/pipeline/    → pi.py, text.py, phases.py, __main__.py, kb.py, learn.py
factory/tests/       → test_pi, test_text, test_phases, test_pipeline, test_integration…
factory/BACKLOG.md   → changelog — mark ✅ with commit, never delete
AGENTS.md            → guards-around-the-loop list — update when a guard changes
tasks/round7/        → this spec + issues.md
```

## Code Style

Match the file you are editing. House rules already in force:

```python
# comments cite the backlog item and say WHY, never narrate the what:
# #34: the summary must not lie — blocked is rebuilt from KB blocker
# nodes because the in-memory list is gone after a crash/resume.
```

- Markers stay `re.M`-anchored at line start (text.py contract).
- `warn/err/ok/log` from `pipeline.pi` for console narration.
- Every guard is fail-closed: absence of signal is never success.

## Testing Strategy

- Unit tests live in the existing file per module (`test_pi.py` for pi.py,
  `test_phases.py` for phases.py, `test_pipeline.py` for verify behavior,
  `test_text.py` for parsers, `test_integration.py` for end-to-end
  scenarios via the fake-pi stub).
- TDD per issue: red test first → minimal green → no regressions.
- Full suite green after every issue before committing (baseline: 142 OK).

## Boundaries

- Always: one issue at a time, suite green before each commit, BACKLOG ✅
  with commit hash, AGENTS.md guard list updated when a guard changes.
- Ask first: changing models.json routing, touching addyosmani skills
  (`.agents/skills/`), deleting anything not listed in an issue.
- Never: weaken an existing guard to make a test pass, mark ✅ without a
  real test run, commit with `git add -A` at the repo root.

## Success Criteria

1. `python3 -m unittest discover -s tests` green, count ≥ 142, no skips
   introduced by these changes.
2. BACKLOG items #34 #35 #38 #39 #41 #42 + both hardening ideas marked ✅
   with their commits.
3. `git log --oneline` shows one commit per issue, message style matching
   history (`fix: …` / `refactor: …` + issue tag).
4. No behavior change beyond what each item describes.

## Open Questions

None — designs are pinned per issue in `issues.md`. #8/#25 (live e2e
confirmation) remain the pomodoro-relaunch's job, pending Jairo's go.