# Round-7 issues — close out the open backlog

Built from `factory/BACKLOG.md` open items after round-6 (2026-09-06).
One commit per issue. Suite must be green before each commit.

## Issue #1: #34 — `--resume` summary must report real blocked issues

The final summary prints `len(blocked)` — but on resume, `blocked = []` by
definition (phase 3 skipped), so the summary says "0 blocked" even when the
KB has blocker nodes from the crashed run. The summary lies.

**Design:** rebuild the blocked list from KB `blocker` nodes. In
`__main__._run`, when phase-3 is done via resume, query
`kb.query(type_="blocker")` and extract issue numbers from summaries that
match `Issue #(\d+)` (the degenerate/blocker node summaries use this
shape: "Issue #N degenerate output", "Issue #N blocked after diagnosis",
"Issue #N skipped after diagnosis", "Regression failure before issue #N",
"Phase 3 halted: unrepairable suite"). Report those numbers; never claim
zero when the KB says otherwise.

**Acceptance criteria:**
- After a `--resume` run over a project whose KB has blocker nodes with
  issue numbers, the summary lists those issue numbers, not 0.
- Blocker nodes without an issue number (e.g. "Pipeline halted by stop.md")
  are counted in a separate total but don't fabricate numbers.
- Fresh (non-resume) runs keep current behavior.
- Unit-testable: an integration scenario or a unit test on the summary
  builder with a real KB fixture.

**Dependencies:** none.

## Issue #2: #35 — interactive interview has no timeout

`run_pi(interactive=True)` uses `Popen` + `p.wait()` with no limit. A hung
pi/Ollama call freezes phase 0 forever; the #10 timeout only covers the
non-interactive path (`subprocess.run` + timeout).

**Design:** apply `PI_TIMEOUT` to the interactive path too. With
`subprocess.Popen` there's no `timeout=` param on `wait()` — use
`p.wait(timeout=PI_TIMEOUT)` (Python 3.3+ supports it) wrapped in
`try/except subprocess.TimeoutExpired`: kill the process group
(`os.killpg(p.pid)` — the interactive child already runs as its own
session via start_new_session... verify: it doesn't; plain Popen. Kill
the process and its children with `p.kill()` after `terminate()`
escalation), treat the timeout as "no answer" (empty return flows into
degenerate guards), warn loudly. The human may also abandon the interview
naturally (EOF/Ctrl-D) — that path must keep working: `p.wait(timeout=...)`
raises only on wall-clock timeout, EOF ends the stream and wait returns.

**Acceptance criteria:**
- A hung interactive call returns within PI_TIMEOUT (not forever), with a
  loud warn, and phase 0 falls through to the #45 close-out path.
- EOF/Ctrl-D abandonment keeps the current behavior (stream ends, phase 0
  proceeds to close-out).
- Unit test with a patched `subprocess.Popen` or a fake that never exits,
  asserting the empty return + warn within a tiny timeout env
  (`SIESTA_PI_TIMEOUT` patched small).

**Dependencies:** none.

## Issue #3: #38 — pipeline artifacts pollute generated project repos

`pre_issue_*.json`, `*_output.txt`, `regression_*.log`,
`learning_issue_*.txt`, `project_learning.*`, `verify_verdict.txt` (already
there), `interview_closeout.txt`, `.pipeline-checkpoint` (already there)
land in project commits via `_commit()`'s `git add -A`.

**Design:** extend the hygiene `.gitignore` written at project init in
`__main__._run` with the artifact patterns. One decision to pin: the
artifacts must still be written to disk (they are run evidence and the
learner reads them — `learn.py` reads `issue_{n}_output.txt` from disk);
only the COMMIT is unwanted. So: gitignore patterns, not a move to a
subdirectory. Patterns: `*_output.txt`, `regression_*.log`,
`pre_issue_*.json`, `learning_issue_*.txt`, `project_learning.*`,
`interview_closeout.txt`, plus existing entries. Keep `spec.md`,
`issues.md`, `README.md`, `requirements.txt`, `kb/`, `tests/`, source
committed — they are the product and its memory.
Verify the .gitignore change alone is enough: after a fake-pi integration
run, `git ls-files` must not list any `*_output.txt` in the generated repo.

**Acceptance criteria:**
- After a full fake-pi run, `git ls-files` in the generated project shows
  no `*_output.txt`, no `regression_*.log`, no `pre_issue_*.json`, no
  `learning_issue_*.txt`, no `project_learning.*`.
- `spec.md`, `issues.md`, `kb/` and source files stay committed.
- The learner still finds its inputs on disk (`learn.py` reads them).
- Integration test asserts the gitignore content + `git ls-files` empty of
  artifacts.

**Dependencies:** none.

## Issue #4: #39 — `gather()` has no total budget

`gather()` reads head 500 lines per file across every source file. A big
project makes the worker/verify/review prompt grow unbounded — the model's
context floods and output quality collapses.

**Design:** add a total cap in characters (prompt budget). Iterate files
in a deterministic order (already sorted), accumulate content, stop
appending when the budget is exhausted, append a truncation notice naming
the remaining file count. Budget: `GATHER_BUDGET = 120_000` characters
(~30k tokens, comfortable for GLM/gemma4 context while bounded). Keep
per-file cap at 500 lines. When a file partially fits, include its head
that fits — do not mid-file truncate silently without the notice.

**Acceptance criteria: |
- `gather()` output length is bounded by GATHER_BUDGET + the notice, for
  any project size.
- Small projects: identical behavior to today (no notice, full content).
- Truncation emits a visible notice with the count of files not included.
- Unit tests: small project unchanged; huge project bounded + notice.

**Dependencies:** none.

## Issue #5: #41 — `review()` lacks the degenerate guard

`review()` is the only "silence = success" phase without the degenerate
guard: if the review output has no REVIEW_PASSED/REVIEW_FAILED marker it
only warns, then hands the raw output to the proxy — the proxy then decides
on garbage. Family A (#2/#11/#12/#13/#15).

**Design:** treat degenerate review output exactly like verify does (#11):
if no marker AND `text.degenerate(review_out)`, skip the proxy gate and
run one worker-driven repair pass with write tools (the #16 machinery:
same skills, same fix prompt shape), then commit. Never approve garbage.
If the output is degenerate, the proxy never sees it as a verdict basis.
If degenerate after the fix pass too — warn and keep the honest state
(review not passed), but do not block the pipeline (review is not a
halting gate by design — verify is the gate that halts honesty).

**Design refinement (self-review):** the proxy gate itself stays as-is for
non-degenerate marker-less output (PROXY sees it, fails closed) — the fix
targets only the degenerate case.

**Acceptance criteria:**
- Degenerate review output (tool JSON, asks-human) never reaches the proxy
  as a verdict basis.
- Degenerate → one repair pass with write tools + commit, mirroring #16.
- Marker present (PASSED or FAILED): unchanged behavior.
- Unit/integration test feeding degenerate review output.

**Dependencies:** none.

## Issue #6: #42 — dead code and UX cleanups

Small, independent removals/merges. All are behavior-preserving refactors
unless the item says otherwise:

**Design:**
1. **PY_PORTS dead value**: `PY_PORTS = [5000, 8000, 3000, 8080]` is
   returned alongside commands but the caller (`runtime_smoke`) never uses
   the port list for non-web commands — it computes `_free_port()`. Delete
   `PY_PORTS`; have `_detect_runnable` return `(cmd, ports)` where ports
   is only ever the web port list (`WEB_PORTS` stays) or `None`.
2. **phase2 return value ignored**: `__main__` calls
   `phases.phase2(...)` without using the issue count. Either consume it
   (log the issue count after plan generation — cheap UX) or drop the
   return. Decision: log it — `phases.phase2` already logs "Plan
   generated"; extend with the count. `__main__` keeps ignoring it (fine).
3. **verify/_verify merge**: `verify()` is a 2-line wrapper around
   `_verify()` persisting the verdict. Merge into one function
   `verify(proj)` that runs + persists; `_verify` disappears. Callers and
   tests reference `phases.verify` (test_pipeline.py) — keep the public
   name `verify`.
4. **Duplicated skills tuples**: `RETRY_SKILLS` and the execute-phase tuple
   share incremental-implementation + test-driven-development. Not worth
   an abstraction for a 2-element overlap per the "three similar lines
   beat premature abstraction" rule — instead, extract the per-role skill
   sets into named constants at module level next to the prompts they
   serve (e.g. `EXECUTE_SKILLS`, `REVIEW_SKILLS`, `VERIFY_SKILLS`) so the
   duplication is visible and greppable.

**Acceptance criteria:**
- `PY_PORTS` gone; non-web smoke still works (test RuntimeSmoke).
- Issue count logged after plan generation.
- `phases.verify` single function; no `_verify` references remain.
- Skills tuples named; no behavior change (integration test green).
- Suite green.

**Dependencies:** none.

## Issue #7: hardening — stderr noise corrupts parsed markers

`run_pi` concatenates `result.stdout + result.stderr` ("Bash piped
everything through 2>&1; models sometimes narrate on stderr"). Provider
noise in stderr (e.g. pi's "Warning: Model ... not found ... Using custom
model id.") flows into the parsed artifact and can corrupt marker
parsing — evidence: pomodoro `verify_output.txt` contains that warning
inside the parsed text.

**Design:** keep stderr OUT of the parsed text; keep the bash-era promise
that narration on stderr isn't lost: log stderr separately when non-empty
(`warn()` one line + append to the artifact under a separator line, or
write `artifact.with_suffix(".stderr.txt")`? — pin: append to the artifact
after the parsed content with a `PROVIDER_LOG:` separator line so the
run evidence stays in one file but BELOW the parsed region. The parsers
match anchored markers at line start; a suffix cannot corrupt parsing of
the upstream content. BUT verify() appends RUNTIME_CHECK to
verify_output.txt AFTER run_pi wrote it — appending stderr below that
would still be fine (order: model output, stderr separator, RUNTIME_CHECK).

Wait — simpler and safer: stdout is the model answer; stderr is provider
noise. Parse stdout only. If stderr is non-empty, `warn()` it (truncated)
and write it to the artifact below a `\nPROVIDER_LOG: ...\n` separator.
Tests: a fake pi emitting markers on stdout + noise on stderr must parse
clean; noise containing a marker-like line on stderr must NOT parse as a
verdict.

**Acceptance criteria:**
- `run_pi` returns stdout only.
- Non-empty stderr: warned (head) + persisted in the artifact below a
  `PROVIDER_LOG:` separator (below everything run_pi writes).
- A stderr line like `VERIFY_PASSED:` does not change the verdict.
- Unit tests in test_pi.py with a fake subprocess result.

**Dependencies:** none.

## Issue #8: hardening — markers inside fenced code are false positives

Marker parsers (`REVIEW_*`, `VERIFY_*`, `CONSULT`, `PROXY_REQUEST`) match
markers the model quotes as examples inside fenced code blocks — fence
content sits at column 0 so the `^` anchor doesn't help. `spec_doc()`
already solved this shape for spec/plan parsing (#36): strip tagged fence
regions before matching.

**Design:** in `text.py`, add `strip_code_fences(text) -> str` as a small
public wrapper around the existing `_strip_code_fences` (it already cuts
language-tagged fence regions, keeps bare fences and doc-tag fences) —
wait, for markers the requirement is different: a marker quoted inside
ANY fence (bare or tagged) is quoted, not spoken. But bare fences may
legitimately wrap the whole document (unwrap_fences handles the enclosing
case). Pin the decision: markers are matched against the text with ALL
fenced regions (bare or tagged) cut — quoted content is never a protocol
signal. The enclosing-fence unwrap in spec/plan parsing happens before
doc extraction; for markers, cut all fences directly.

**Design refinement:** add to text.py: `def without_fences(out: str) -> str`
— cut every fenced region (bare ``` and tagged ```lang) including markers.
Then `phases.py` marker-gates for review/verify/consult/proxy use
`text.without_fences(out)` before regex search. Apply to the gates where
quoted examples are plausible: review marker check, verify marker check,
CONSULT/PROXY search in execute, LEARN/SKILL parsing in learn.py (a
SKILL_UPDATE block quoted as an example must not rewrite a skill!).

**Acceptance criteria: |
- A `VERIFY_PASSED:` inside a fenced block is not a verdict.
- A `CONSULT:` inside a fenced block does not trigger escalation.
- A `SKILL_UPDATE_START` block inside a fence cannot rewrite a skill.
- Real markers OUTSIDE fences still match (regression: suite green).
- Unit tests in test_text.py for without_fences + gate behavior tests.

**Dependencies:** Issue #7 (same file area, text pi.py/artifacts; land
after to avoid conflicts).

## Issue #9: docs — sync AGENTS.md guard list + BACKLOG close-out

AGENTS.md "Guards around the loop" lists guards; round-7 added/changed
several (interactive timeout, review degenerate guard, stderr separation,
fence-aware markers). BACKLOG.md: mark all round-7 items ✅ with commits,
note #8/#25 still pending the pomodoro relaunch, round-7 section header.

**Acceptance criteria:**
- AGENTS.md guard list reflects the new guards with issue tags.
- BACKLOG has a Round-7 findings section with ✅ + commits.
- No code changes.

**Dependencies:** Issues #1–#8 all merged.