# Siesta — Backlog of Corrections & Improvements

Living backlog. Sources: live e2e runs (`factory/projects/<name>/` artifacts) and
code walkthroughs. When an item is done, mark it ✅ with the commit instead of
deleting it — this file is also the changelog of what Siesta learned about itself.

## P0 — Blockers (fix before the next e2e run)

- [x] **B1. models.json routing regression.** Working tree has all three roles on
  `qwen2.5-coder:latest`; design is GLM-5.2 (planner/consultant) + qwen (worker).
  All-qwen e2e runs fail at phase 1/2: qwen can't hold the text protocol
  (hallucinated an unrelated "Task Manager" spec for a Caesar-cipher idea;
  emitted tool-call JSON instead of VERIFY markers). Decision needed: restore GLM
  routing vs. stay all-local and harden the text protocol.
  ✅ fixed in ab8bce7: GLM-5.2 routing restored (the all-qwen config was an
  obsolete workaround; the directive-last prompt shape is the real fix).
- [x] **B2. KB split.** Principles "Use english" + "Verify pushes contain no PI"
  landed in stray nested `factory/factory/kb/global-graph.json` (seeding ran with
  a relative path from cwd `factory/`). Root KB never sees them. Merge nodes into
  `factory/kb/global-graph.json` and delete the stray directory.
  ✅ fixed in ab8bce7: 2 principle nodes merged, stray dir deleted (9 nodes).
- [x] **B3. `.gitignore` dropped `.pi/`** (commit 1519f64 had added it). `.pi/` is
  untracked and pushable — violates the user's own no-PI principle. Restore
  before any commit/push.
  ✅ fixed in ab8bce7: .pi/ back in .gitignore.

## Round-2 findings (from e2e run 2 + walkthroughs)

- [x] #1 GLM builds the whole app during spec/plan despite "do NOT write code".
  Mitigated: retro-spec + generic FALLBACK_ISSUE recovery (phases.py ~167-248).
- [x] #2 "Issue #N executed" false positive: `ok(f"Issue #{num} executed")`
  (phases.py:409) fires on degenerate/terminated worker output — no
  degenerate-output guard. Pair with a minimum-substance check on the worker
  output.
  ✅ fixed in the family-A batch: degenerate worker output gets one feedback retry, then the issue is blocked — no fake completion node.
- [x] #3 Proxy gate fail-open: anything ≠ NEEDS_REVISION counts as approval
  (phases.py:537). Approves helpless narrations. Should require an explicit
  APPROVED marker.
  ✅ fixed in the family-B batch: issue-level proxy gates now require an explicit line-start APPROVED marker; REJECTED → retry, and NEEDS_REVISION/hesitation/garbage also retry with feedback — never approval.
- [x] #4 `_detect_runnable` misses `python -m <pkg>` (package with
  `__main__.py`).
  ✅ fixed in the family-D/E batch: _detect_runnable() now finds packages with __main__.py and runs them as `python -m <pkg>` — the layout the pipeline itself generates.
- [x] #5 Retro `issues.md` template hardcoded for the previous (HTML) project.
  Fixed.
- [x] #6 Phase 6 commits "Project verified" even when verdict = VERIFY_FAILED
  (__main__.py:169-171); resume path also hardcodes VERIFY_PASSED
  (__main__.py:161). Tie the decision node + commit message to the actual
  verdict.
  ✅ fixed in the family-B batch: verify() persists its verdict to verify_verdict.txt; resume reads it instead of hardcoding VERIFY_PASSED, and phase 6 records decision+commit or blocker+UNVERIFIED commit per the real verdict.
- [x] #7 Generated projects commit `.DS_Store`/`__pycache__`/`.pipeline-checkpoint`
  (`git add -A`, no .gitignore). Write a standard .gitignore at project init.
  ✅ fixed in the family-D/E batch: project init writes a hygiene .gitignore (.DS_Store/__pycache__/*.pyc/.pipeline-checkpoint/verify_verdict.txt) before the first `git add -A`.
- [ ] #8 Learners emit 0 parseable learnings even with `--no-tools` (root KB has
  only failure nodes). Root cause: prompt format vs `learn.py` parser mismatch.
  🔶 root causes fixed (#14 parser, #17 stale skill CLI); keep open until the
  next live e2e confirms parseable learnings.
- [x] #9 `execute()` is not per-issue idempotent (found in code walkthrough,
  2026-08-31). A crash mid-phase-3 re-runs ALL issues on `--resume`, ignoring the
  3 completion records already on disk (KB "Issue #N completed" decision node,
  `🔧 Issue #N` git commit, `issue_N_output.txt`); in-memory `fails`/`history`/
  `blocked` (phases.py:380) are lost. Fix sketch: skip issues that already have a
  completion node in `kb.query(type_="decision")` (~3 lines in the execute loop).
  Nice emergent behavior: blocked issues lack the node, so they naturally retry.
  ✅ fixed in the family-D/E batch: execute() is per-issue idempotent: issues with an existing 'Issue #N completed' decision node are skipped on resume; blocked issues have no node and naturally retry.
- [x] #10 `run_pi()` has no timeout (found in code walkthrough, 2026-08-31).
  A hung `pi`/Ollama call freezes the pipeline forever; `stop.md` can't help
  because it is only checked between issues. Add `timeout=` + a retry policy.
  Same family as #2: the pipeline assumes calls terminate and tell the truth.
  ✅ fixed in the family-D/E batch: run_pi() enforces SIESTA_PI_TIMEOUT (default 1200s); a timed-out call returns empty so the degenerate guards treat it as a failed attempt — a hung call can no longer freeze the pipeline.
- [x] #11 Verify phase accepts degenerate output: the landing-page e2e run
  "completed" exit 0 while `verify_output.txt` contains tool-call JSON and no
  VERIFY marker at all. Same failure family as #2 but in `phases.verify()` —
  the degenerate-output guard (or the mechanical fallback deciding "passed")
  treats absence of signal as success. Evidence:
  `factory/projects/build-a-modern-landing-page-website/verify_output.txt`.
  ✅ fixed in the family-A batch: degenerate verify output (no usable marker) is decided by the mechanical fallback only; an explicit marker stays the primary signal.
- [x] #12 `intent_from()` fail-open, silent (found in code walkthrough,
  2026-08-31): if the phase-0 interview ends with no `INTENT_FINALIZED:` marker,
  the raw idea is used as intent with NO warning (phases.py:115, text.py:48-64).
  A degenerate interview (model narrated, never concluded) looks identical to a
  clean one. Same "absence of signal = success" family as #2/#3/#11. Fix sketch:
  warn (or retry the interview once) when the marker is missing.
  ✅ fixed in the family-A batch: the interview warns loudly when INTENT_FINALIZED is missing (raw idea is a fallback, not a success).
- [x] #13 Regression suite green on absence (found in code walkthrough,
  2026-08-31): `run_regression()` returns True when there is no `tests/` dir or
  no known runner (phases.py:273, 277). "No tests" is silently treated as
  "nothing broke" — a worker that skipped writing tests gets the same green
  light as one that did. Fix sketch: record tests-missing as a KB blocker or
  make the TDD prompt enforce test presence per issue.
  ✅ fixed in the family-A batch: run_regression() returns passed/failed/skipped; 'skipped' (no tests/no runner) warns and never reads as green.
- [x] #14 (root cause for #8): the `LEARN` parser format is too strict — it
  requires `TAG: summary — detail` with an em dash `—` and a mandatory detail
  (text.py:24-26). Learners emitting `-`/`–` or summary-only lines produce zero
  matches → "0 parseable learnings". Fix sketch: accept `—`, `-`, `–` as
  separators; make detail optional (default to summary).
  ✅ fixed in the family-C batch: LEARN accepts `—`/`–`/`-` and an optional
  detail; summary-only lines log with empty detail.
- [x] #15 Regression failure doesn't gate execution (found in code walkthrough,
  2026-09-02): when the regression suite actually fails (returncode != 0),
  `execute()` only writes a KB blocker node and proceeds to run the issue anyway
  (phases.py:390-392). The suite is a witness, not a guard: building continues
  on top of a broken state. Fix sketch: skip the issue (append to `blocked`)
  or retry the previous issue's fix before continuing.
  ✅ fixed in the family-A batch: a red regression suite gates the next issue (blocked + KB node) — the suite is a guard, not a witness.
- [x] #16 Review "fix" pass is a no-op (found in code walkthrough, 2026-09-02):
  when the proxy requests revision, the pipeline runs the worker with
  "Fix the issues now" but `tools="no"` (phases.py:539-543) — the worker
  cannot write files, so "fixes" land in `review_fixes_output.txt` and are
  NEVER applied. `ok("Review complete")` follows unconditionally. Invalidates
  phase 4's purpose. Fix sketch: give this pass write tools (like the execute
  phase), and re-commit after it.
  ✅ fixed in the family-B batch: the review-fix pass runs with write tools (like execute) and commits its changes afterwards; degenerate fix output warns.
- [x] #17 All 5 factory skills reference the deleted `kb-manager.sh` CLI
  (found in code walkthrough, 2026-09-02): human-proxy, kb-manager,
  issue-executor, factory-learner, consultant-protocol contain 30+ calls to
  `kb-manager.sh ...` — the script was deleted in the Python port; the
  replacement is `python3 -m pipeline.kb`. Models following the skills verbatim
  hit a failing command and may silently skip KB logging. Likely root cause (or
  contributor) of #8. Fix sketch: sed-replace `kb-manager.sh <args>` with
  `python3 -m pipeline.kb <args>` across factory/skills/ and verify shim
  arg-compat (query/get-node/append-node/append-edge/init-project).
  ✅ fixed in the family-C batch: all 33 references sed-replaced to
  `python3 -m pipeline.kb` (shim-compatible args), one prose `post-issue.sh`
  mention fixed too; run_pi() now exports the factory dir on PYTHONPATH so
  the shim works from any project cwd; test_skills.py guards regressions
  (no deleted CLI names, only supported shim subcommands).
- [x] #18 (minor) Review gate uses a raw substring check `"NEEDS_REVISION" in
  proxy_out` (phases.py:537) instead of an anchored marker like `text.REJECTED`
  — accidental mentions trigger revision requests. Make proxy gates use the
  same anchored-marker style as the rest of the protocol.
  ✅ fixed in the family-B batch: the review gate uses the anchored APPROVED marker (text.APPROVED) instead of a raw substring.
- [x] #19 Runtime smoke is HTTP-only and punishes working CLIs (found in code
  walkthrough, 2026-09-02): `runtime_smoke()` probes with `urlopen` — a CLI
  that starts, prints and exits cleanly (exit 0) is reported as
  `FAILED: process exited with code 0` (phases.py:599-600). Any detected CLI
  project is misjudged as broken. Combined with #4 (narrow detection), only
  web projects get a meaningful smoke. Fix sketch: for non-web entry points,
  treat "exited 0 within N seconds" as PASSED and "non-zero exit / crash" as
  FAILED; keep the HTTP probe only for `npm start`/server-ish projects.
  ✅ fixed in the family-D/E batch: runtime_smoke() gives non-web entry points CLI semantics: clean exit 0 = PASSED, crash = FAILED, still-running = started cleanly; the HTTP probe stays only for npm start/http.server.
- [x] #20 Skill self-modification has no safety net (found in code walkthrough,
  2026-09-02): `apply_skill_updates()` (learn.py:38-50) does a full
  `write_text` of the SKILL.md with zero validation — a truncated/garbage
  block body silently wipes or guts a factory skill; `name.replace("/", "")`
  blocks slash traversal but `.`/`..` names escape the target dir. Only real
  protection is git, and factory skill changes are currently uncommitted.
  Fix sketch: validate the block (non-empty, frontmatter present, plausible
  length), reject `.`/`..`, and auto-commit factory/skills before applying.
  ✅ fixed in the family-C batch: apply_skill_updates() rejects unsafe names
  (`""`/`.`/`..`) and blocks that don't look like a complete SKILL.md
  (frontmatter + >=50 chars), logging every rejection instead of wiping.
- [x] #21 Spec template hallucination passes the format check (round-3 e2e,
  2026-09-02, GLM): for the council-CLI idea GLM emitted a generic
  'Project name: TBD / Author: TBD' shell spec — spec_doc() validated headings
  and fences but not content. ✅ fixed in the round-3 batch: new
  text.shares_content() relevance guard — a spec sharing no content word with
  the intent is rejected, with one SPEC_RETRY_DIRECTIVE feedback retry before
  the honest abort.
- [x] #22 Plan format drift has no retry (round-3 e2e, 2026-09-02, GLM): the
  planner emitted priority sections with '### 1.' headers instead of the
  required '## Issue #N:' — issues_doc() (correctly) refused it and the
  pipeline aborted with no retry. ✅ fixed in the round-3 batch: one
  PLAN_RETRY_DIRECTIVE feedback retry demanding the exact header format
  before the fallbacks; both spec and plan prompts now forbid templates/
  priority groupings explicitly.

## Family map (2026-09-02, after full code walkthrough)

- A "silence = success": #2 #11 #12 #13 #15 — absence of signal read as approval
- B fail-open gates: #3 #16 #18 (+ part of #6) — gates need explicit signal to STOP
- C fragile protocol: #8 #14 #17 #20 — text↔model contract trusted too much
- D resilience: #9 #10 — crashes and hangs don't recover
- E mechanical detection: #4 #19 — verifier can't see what the generator produces
Attack plan: P0 blockers → C (cheap, unblocks learning) → A (one shared
degenerate-output guard + fail-closed defaults) → B → D → E. Each fix ships
with a fake-pi test feeding degenerate output; the 68-test suite stubs the
model as protocol-compliant, which is why these survived it.

## Related hardening ideas (from walkthroughs, not yet findings)

- [x] run_pi() concatenates stdout+stderr into the parsed text. Provider noise in
  stderr can corrupt marker parsing. Consider tagging/filtering stderr before
  parse, or logging stderr separately from the artifact. Evidence: pomodoro
  `verify_output.txt` contains `Warning: Model "qwen2.5-coder:latest" not
  found for provider "ollama". Using custom model id.` — pi stderr noise inside
  the parsed artifact; it also flags that calls may not run the intended model.
  ✅ fixed in a918325 (round-7): `run_pi()` parses stdout only; non-empty
  stderr is warned (head) and persisted in the artifact below a
  `PROVIDER_LOG:` separator — evidence stays in one file, below the parsed
  region, so a stderr `VERIFY_PASSED:` can never falsify a verdict. The
  "not found for provider" warning still surfaces as a loud warn.
- [x] Marker parsers (`REVIEW_*`, `VERIFY_*`, `CONSULT`, `PROXY`) accept markers
  inside fenced code blocks the model quotes as examples (false positives) —
  fence content sits at column 0 so the `^` anchor doesn't help. `spec_doc()`
  already solves this for spec/plan by cutting code-fence regions (#36);
  reuse that approach (ignore code-fence regions before matching).
  ✅ fixed in 59d6b64 (round-7): new `text.without_fences()` cuts EVERY fenced
  region (bare or tagged, unclosed cuts to end) — quoted content is never a
  protocol signal. The worker gates (CONSULT/PROXY in execute + `_escalate`,
  including every fed-back retry), review/verify marker checks, and the
  learner parses (LEARN/SKILL_UPDATE — a quoted block can no longer rewrite
  a factory skill) all match fence-free. Integration scenario `verify_fenced`:
  a fenced VERIFY_PASSED no longer certifies.

## Round-5 findings (2026-09-05 — full code walkthrough, fixes same day)

- [x] **#28 Two live `Graph` instances over the global KB — phase 7 wipes the
  run's per-issue learnings.** `__main__._run` creates `gkb` at start and keeps
  it all run; `phases.execute()` creates a second instance that writes the
  per-issue learnings; phase 7 then saves through the FIRST (stale) instance,
  rewriting global-graph.json without the nodes written since it loaded. The
  "latent" note above was wrong — this fired on every run reaching phase 7
  (evidence: the Sep-5 run's learning nodes existed on disk, at risk the
  moment phase 7 ran). The BACKLOG family it belongs to: C (fragile protocol
  trust) — the code trusted its own in-memory cache.
  ✅ fixed: `Graph` now re-reads the file on every operation (load-modify-save
  per call — the graphs are tiny); two regression tests in test_kb.py.
- [x] **#29 `post_issue` logs the FIRST attempt, not the final one.** A success
  that arrived via retry/diagnosis wrote the degenerate first output into the
  "Issue #N completed" decision node.
  ✅ fixed: `post_issue` takes the final worker output (in memory), not
  `issue_{n}_output.txt`.
- [x] **#30 `runtime_smoke` inherits the pipeline's stdin** — a CLI that reads
  stdin hung until the deadline and read as "PASSED (started cleanly)".
  ✅ fixed: `stdin=subprocess.DEVNULL` on the smoke Popen.
- [x] **#31 `_commit` fails silently** — no returncode check; a repo without
  git identity produced runs that "completed" with an empty git history.
  ✅ fixed: commit failures warn with git's stderr.
- [x] **#32 Project-level skill actions logged "(issue #None)"** —
  `act_on_learnings(..., n=None)` from phase 7 wrote the literal None into
  KB summaries.
  ✅ fixed: n=None logs "(project level)".

Remaining round-5 walkthrough findings (not yet fixed, candidates for round-6):

- [x] **#34 `--resume` reports 0 blocked issues** — `blocked = []` is set by
  definition when phase-3 is done; the summary lies. Rebuild from KB blocker
  nodes.
  ✅ fixed in 707d336 (round-7): `_blocked_from_kb()` rebuilds the list from
  blocker nodes on resume — issue numbers from summaries ("Issue #N …",
  "Regression failure before issue #N"), minus issues that later completed
  (completion outranks a stale blocker, mirroring #9's idempotency);
  run-level blockers without a number stay out of the count. Integration
  test: a blocked run resumed reports the same "2 blocked".
- [x] **#35 The interactive interview has no timeout** — the #10 fix only
  covers the non-interactive path (`Popen` + `p.wait()` without a limit).
  ✅ fixed in f7b5e19 (round-7): `p.wait(timeout=PI_TIMEOUT)` on the
  interactive path; on expiry the child is killed, the partial transcript
  is kept and returned as the (degenerate) answer — phase 0 flows into the
  #45 close-out path. EOF/Ctrl-D abandonment unchanged. Unit tests with a
  hang-Popen fake.
- [x] **#36 `_strip_indented_fences` rejects any spec containing one tagged
  fence** (```python etc.) — trades the run-4 false negatives for false
  positives: a legit spec showing one CLI example dies whole. Consider a
  fenced-lines ratio, or stripping instead of rejecting.
  ✅ fixed: `spec_doc()` now CUTS language-tagged fence regions (marker +
  content) before the heading check instead of rejecting the whole spec —
  a spec with a small ```python example parses, but fenced lines never
  reach spec.md, so a fenced '###' can no longer pose as a spec heading
  (run-4's smuggle dies at the fence, and an answer fenced whole as code
  is still rejected as a dump). Bare ``` fences and ```markdown-style
  wrappers stay content/illustration. Plan parsing (`issues_doc`) never
  shared the reject logic, so no false positives there. Unit tests in
  test_text (DocExtraction) updated: 139 tests green.
- [x] **#37 The learner runs as `worker` (qwen local, thinking off)** — the
  weakest model owns the strictest output format. Route learning calls to
  `consultant` (GLM) if #8-style parse problems return.
  ✅ fixed via #46 (round-6): the pomodoro run reproduced the parse problems
  (verbose unparseable LEARNING blocks), and `learn_issue()`/`learn_project()`
  now call the consultant role (GLM 5.2).
- [x] **#38 Artifacts pollute generated repos** — `pre_issue_*.json`,
  `*_output.txt`, `regression_*.log` land in project commits via `add -A`;
  extend the generated .gitignore or move them under `.pipeline/`.
  ✅ fixed in 0cb50e9 (round-7): the hygiene .gitignore written at project
  init now also ignores `*_output.txt`, `interview_closeout.txt`,
  `regression_*.log`, `pre_issue_*.json`, `learning_issue_*.txt`,
  `project_learning.*`. Files stay on disk (learn.py reads them as
  inputs) — only the commits are clean. Integration test asserts
  `git ls-files` is artifact-free and the inputs still exist.
- [x] **#39 `gather()` has no total budget** — 500 lines per file × every
  source file per call; the worker prompt grows unbounded. Cap the aggregate.
  ✅ fixed in bee7724 (round-7): `GATHER_BUDGET = 120_000` chars (~30k
  tokens); files added in deterministic order until the budget is spent, a
  partial file keeps the head that fits with a "(file cut mid-way)" marker,
  and a `TRUNCATED: N further source files not shown` notice ends the
  gather. Small projects: byte-identical behavior (no notice, full files).
- [x] **#40 `shares_content` passes on one shared word** ("python" alone
  validates any Python spec). Require ≥2 shared words or a ratio.
  ✅ fixed: `shares_content()` now requires at least TWO shared content words,
  except when the intent itself has fewer than two content words — then one
  match is all an honest spec can offer, and a contentless intent passes
  vacuously (`min(2, len(intent words))`); phase1's warn reworded to "shares
  too little content". Four new unit tests in test_text (ContentRelevance);
  the old 1-word fixture moved to the 2-word contract. 139 tests green.
- [x] **#41 `review()` skips the degenerate guard** — the only "silence =
  success" phase without it (marker absence only warns, then proxy decides).
  ✅ fixed in ec27caf (round-7): degenerate review output (no marker +
  tool-speak/asks-human) never reaches the proxy — the #16 fix pass runs
  with write tools instead, a KB blocker records the unusable verdict, and
  the fixes are committed. Marker-less but non-degenerate output keeps the
  fail-closed proxy gate. Integration scenario `review_degenerate`.
- [x] **#42 Dead code/UX**: `PY_PORTS` unused since #19; `phase2`'s return value
  ignored; duplicated skills tuples; `verify`/`_verify` merge; the duplicate
  BACKLOG entry (removed in this round).
  ✅ fixed in 1b49a01 (round-7): `PY_PORTS` deleted (CLI smokes need no port
  list — runtime_smoke computes its own); `_verify` merged into `verify()`
  (one function, verdict persisted at the end, public name unchanged);
  per-phase skill sets are named constants (`EXECUTE_SKILLS`, `REVIEW_SKILLS`,
  `REPAIR_SKILLS`, `VERIFY_SKILLS`) next to `RETRY_SKILLS`; phase2's issue
  count is now logged by the orchestrator ("Planned N issues") and pinned by
  a unit test.
- [x] **#43 `Graph.edge()` validates nothing** (carried over from the hardening
  list) — any from/to/kind passes, even dangling node ids.
  ✅ fixed: `edge()` now raises ValueError when `kind` is not in the schema's
  `edge_types` (mirroring `node()`'s convention) or when either endpoint id
  is not a node in the graph; the CLI `append-edge` shim prints the error and
  exits 1 like `append-node`. Unit tests in test_kb (GraphEdges); the
  test_phases fixtures used synthetic dangling ids ("n1") and now create a
  real intent node. 135 tests green.

## Round-6 findings (2026-09-06 — first gemma4 e2e: the pomodoro run)

Run: `./factory/bin/siesta.sh "Build a POMODORO app toe xecute in my Mac"`.
Result: 12 issues, **11 skipped** by the regression gate, app delivered as a
`pass` stub, UNVERIFIED — from a single scaffold stub. Evidence:
`factory/projects/build-a-pomodoro-app-toe-xecute-in-my/` (all 11
`regression_N.log` files identical: "collected 0 items", pytest exit 5).

- [x] **#44 The regression gate cannot tell "red" from "empty" — and skips
  instead of repairing.** Issue #1 (scaffold) legitimately created an empty
  `tests/test_macpomodoro.py` — its own acceptance criteria said "pytest
  collects zero tests without error". pytest exits **5** on "no tests
  collected"; `run_regression()` treated any non-zero exit as FAILED, so the
  gate armed itself on an *empty* suite and skipped every remaining issue —
  11 skips, zero repair attempts, no halting, review/verify on a stub.
  Two defects, both fixed:
  1. `run_regression()` now treats pytest exit 5 as `skipped` (absence, not
     breakage — same family as #13).
  2. A genuinely red suite now gets ONE worker-driven repair attempt
     (`_repair_regression`, same treatment as a stuck worker), then an honest
     skip-with-blocker; **two consecutive unrepairable suites halt phase 3**
     (exit 1) instead of skipping the whole plan on a broken base. Only a
     green (`passed`) suite resets the streak — "fixed by deleting the
     tests" cannot disarm the breaker.
  ✅ fixed: unit tests (test_phases) + 3 integration scenarios
     (repair_regression / repair_fails_forever) — 125 tests green.
- [x] **#33 `_detect_runnable` misses single-file CLIs** — the pomodoro app
  (`macpomodoro/macpomodoro.py`, the planner's own scaffold layout) was
  SKIPPED by the smoke check ("no runnable entry point"). Fixed together with
  #44: detection now covers `<dir>/<dir>.py` and root-level scripts, but only
  when the `__main__` guard body is real work — a scaffold stub (`pass` /
  `...` / comment-only) stays non-runnable, so issue #1 layouts don't count
  as "runs locally" before the app exists.
  ✅ fixed: 4 detection unit tests in test_phases.
- [x] **Race in `gather()` → `FileNotFoundError` mid-run** (found while testing
  #44): `proj.rglob("*")` descends into `.git` while git's auto-gc deletes
  loose objects — iteration crashes the whole phase. `gather()` now prunes
  `.git`/`kb`/`.pytest_cache`/`__pycache__` via `os.walk` (topdown) instead.
  ✅ fixed with the #44 batch; no test repro needed (flaky-by-nature, prune
  is structural).

Round-6 observations (all three fixed in the same round):

- [x] **#45 The interview model never converges.** The interview asked one
  question, the human left (by design), GLM got no answer — and the pipeline
  fell back to the raw idea (`INTENT_FINALIZED` never emitted; #12 warned).
  ✅ fixed: phase 0 now runs ONE autonomous close-out call when the interview
  ends without `INTENT_FINALIZED` — the planner finalizes the intent with
  explicit defaults instead of collapsing to the raw one-liner. Raw idea
  stays the loud fallback only if the close-out also fails. Unit-tested
  (test_phases.AbandonedInterview).
- [x] **#46 Learner still routes to `worker`** (gemma4 local) — see #37; this
  run's learner produced verbose unparseable blocks again (rejected skill
  updates, "process_improvement" learning with no detail).
  ✅ fixed: `learn_issue()` / `learn_project()` now call the `consultant`
  role (GLM) — the strictest output format in the pipeline belongs to the
  model that holds the text protocol. models.json skill lists updated,
  integration call-count assertions adjusted (worker calls drop by the
  learning hooks, consultant calls gain them).
- [x] **#47 Issue #1's plan baked in the trap**: "pytest collects zero tests
  without error" as acceptance criteria conflicts with the TDD skill's "tests
  first" — the planner needs a prompt nudge that scaffold issues must ship at
  least one smoke test.
  ✅ fixed: PLAN_PROMPT now states the plan runs under TDD with a regression
  gate — every issue must leave the suite non-empty and green; a scaffold
  issue includes at least one smoke test, NEVER an empty test file. Unit-
  tested (test_phases: prompt forbids zero-test scaffolds). Belt-and-braces
  with #44: even if the planner disobeys, the gate no longer arms on empty.

## Round-7 findings (2026-09-06 — backlog close-out, TDD per item)

Walkthrough-driven round (no live run): executed every open code item one at
a time, spec + issues in `tasks/round7/`, one commit per issue, suite green
before each. Items closed this round — #34, #35, #38, #39, #41, #42 and both
hardening ideas (stderr noise; fenced markers) — each marked ✅ in its
original section above with its commit:
707d336 f7b5e19 0cb50e9 bee7724 ec27caf 1b49a01 a918325 59d6b64.

Still open after round-7 (live-run items, pending the pomodoro relaunch):

- [x] **#8 Learners emit 0 parseable learnings** — root causes fixed in
  rounds 2-6 (#14 parser, #17 stale skill CLI, #46 GLM routing); closes only
  when a live e2e run produces parseable learnings.
  ✅ confirmed by the pomodoro relaunch (2026-09-06/07): the per-issue
  learner (consultant role, GLM) logged 2 parseable, honest learning nodes
  to the global KB ("Successful scaffold execution", "Successful clean
  execution of helper function issue") — the first live-run learnings since
  the failures. Phase 7 (project-level) never ran in that dead run; #25's
  wordcount run will confirm the full path end-to-end.
- [ ] **#25 Relaunch run-4 after #23 is green** — wordcount idea, then
  confirm #8 with that run too.

## Round-8 findings (2026-09-07 — pomodoro relaunch: the gemma4 context incident)

Relaunch of `build-a-pomodoro-app-to-execute-in-my` (2026-09-06 → 09-07).
Issues #1 (scaffold+smoke) and #2 (format_time) completed with real TDD —
8/8 tests, honest KB nodes (a first: parseable per-issue learnings, see #8).
Then #3/#4/#5 all blocked as "degenerate" (empty stdout; #5 on call
timeout). Root cause, found by hand after the run died: **pi's catalog
declared gemma4 with a 131072-token window while Ollama served it at 8192**
(`/api/ps` `context_length`). pi never compacted, worker prompts overflowed
the real window, `--context-shift` silently dropped the head (skills +
closing directive), and the model ended its turn on a tool call with empty
stdout — exactly what the degenerate guard blocks. Decision: **gemma4 stays
at its real 8K served context** — the fix is honesty, not size.

- [x] **#48 pi catalog lied about the worker's context window.**
  `~/.pi/agent/models.json` said 131072; Ollama served 8192. pi compacts to
  the catalog window, so the lie disabled compaction and silently truncated
  every long worker prompt. Fixes: catalog updated in place (contextWindow
  8192), and a new advisory startup guard — `_warn_context_mismatches()`
  in `__main__.py` probes `GET /api/ps` (the JSON behind `ollama ps`'s
  CONTEXT column — `ollama ps` has no `--format` flag in 0.33.3) for every
  distinct routed model and warns when served < declared. Advisory by
  design: Ollama absent / model idle / catalog unreadable = silence, never
  a halt; verified live both ways (mismatch warn with the old catalog,
  silent after the fix). AGENTS.md documents the true-window registration
  rule and the guard.
  ✅ fixed this round: pi.py (`_served_context`, `_declared_context`,
  `warn_if_context_mismatch`), `__main__._warn_context_mismatches`, catalog.
- [x] **#49 The degenerate guard judges text, not artifacts — blocked
  issues leave real work behind, and the residue can break the committed
  base.** Issues #3/#4 were blocked on degenerate stdout, but the worker
  HAD done real work: `git status` in the project shows `M
  pomodoro_app.py` (+24/-12 — a real partial phase-machine). Worse, the
  residue deleted `format_time` (issue #2's committed, tested work) while
  `test_pomodoro_app.py` still imports it — the tree today fails pytest
  collection (`ImportError`). Two defects: (a) a blocked issue never
  commits or reverts its tree changes, so resume runs against a dirty,
  possibly contradictory base; (b) no check that the working tree is
  consistent with the committed base + tests before the next issue.
  ✅ fixed in round-9: `_discard_residue()` (phases.py) — on block
  (degenerate, diagnosis-skip, stuck-after-diagnosis, red-regression
  skip) tracked files go back to the last commit and untracked product
  files are removed (`git restore` + `clean -fd`, no `-x` so ignored run
  evidence survives); the KB survives — it is the run's bookkeeping, not
  product. Plus the pre-issue guard: a dirty tree at the top of the issue
  loop is restored before any work starts. `regression_repair_*.txt`
  added to the generated .gitignore (the -e clean list had lagged the
  ignore list — evidence must be ignored, then clean preserves it).
  Unit + e2e tested (blocked issues leave zero committed-file residue).
- [x] **#50 Root-level tests are invisible to the regression gate.** The
  pomodoro planner's layout puts `test_pomodoro_app.py` at the project
  root (no `tests/` dir, no requirements/setup/pyproject manifest).
  `run_regression()` hardcodes `tests/` as the suite dir and
  `_regression_command()` requires a manifest — so the gate said "No test
  suite in project" while 8 real pytest tests sat at the root. Issues #2+
  ran unguarded; the scaffold's smoke tests never re-ran.
  ✅ fixed in round-9: `_suite_dirs()` (phases.py) detects suites
  dynamically — root `test_*.py`/`*_test.py` files count as a suite dir
  (`.`) when pytest is importable; `tests/` still counts; every detected
  dir runs (a red one fails the gate). `_regression_command()` takes the
  suite dir, and verify's fallback uses the same `run_regression()`
  instead of its own `(proj / "tests").is_dir()` blindspot. The
  pomodoro-#49 shape (residue breaks root-suite collection) now reads as
  a red suite, not "no suite". Unit + e2e tested.

## Round-4 findings (2026-09-04 — external toolchain regressions, e2e relaunch pending)

Found while monitoring the wordcount e2e relaunch (idea: `--auto "A tiny Python 3
CLI, wordcount.py…"`). The run died in 20s at phase 1 — NOT a pipeline bug: pi
was updated to 0.84.3 since the Sep 2 runs and changed behavior. Evidence smoke
tests (raw `pi` calls, no pipeline involved):

- T1: GLM cloud, data inline in user message → answers correctly ("SLEEZE")
- T2/T2b: qwen WITHOUT explicit `--thinking` → 400 "does not support thinking"
- T2c: qwen WITH `--thinking off` → works ("OK")
- T3: GLM with `--thinking high` → works
- T4: qwen + `--append-system-prompt` → model answers "Qwen" — content lost

- [ ] **#23 pi 0.84.3 drops `--append-system-prompt` content** (pi-wide: both
  glm-5.2:cloud and qwen2.5-coder local). Effect on the pipeline: the spec call
  puts the intent in the system prompt and only the directive in the final
  message → GLM saw the format, not the subject ("You've told me the format…
  but not what the spec is about") and the run failed at phase 1.
  ✅ **fixed in 9aeb01d (114 OK):** `pi.py build_args()` now
  sends `body + "\\n\\n" + user` as one positional prompt (data first, directive
  last — preserves the runs #3/#4 "obeys the last turn" order); `test_pi.py`
  updated. **Pending:** live e2e confirmation (#25).
- [x] **#24 pi default thinking breaks non-thinking models.** Calling pi without
  an explicit `--thinking` sends a level Ollama rejects for qwen2.5-coder (400
  "does not support thinking"). The pipeline is immune — build_args always
  passes `--thinking` explicitly — but the rule is now load-bearing: never call
  pi without an explicit `--thinking`. Also: if models.json ever routes a
  non-thinking model to the deep-diagnosis call (`thinking="high"`), that call
  will 400 — consider a build_args guard that only forwards --thinking when the
  model supports it.
  ✅ fixed in 9aeb01d: `build_args()` guard `_safe_thinking()` forwards the
  requested level only for known thinking models (glm) and pins `off` otherwise,
  so a misrouted deep-diagnosis call (`thinking="high"` on qwen) can no longer
  400; unit-tested both ways.
- [ ] **#25 Relaunch run-4 after #23 is green.** Idea already detailed for
  --auto intent (wordcount.py CLI). Failed attempt artifacts live in
  `factory/projects/a-tiny-python-3-cli-wordcount-py-that/` (interview_output,
  spec_output ×2, failure KB nodes) — relaunch fresh with the same idea, then
  confirm #8 (parseable learner outputs) with this run too.
- [x] **#26 Decide the fate of the 2 never-loaded addyosmani skills**
  (`git-workflow-and-versioning`, `using-agent-skills` — verified: no run_pi
  call loads them). Options: wire git-workflow into review/commit guidance, or
  document both as interactive-human-only in AGENTS.md.
  ✅ decided: document both as interactive-human-only (this batch, AGENTS.md) —
  the Python port commits via `_commit()` in `phases.py`, so wiring them in
  would be decorative.
- [x] **#27 Document `.agents/hooks/*.sh` as bash-era legacy** in AGENTS.md —
  kept per decision (2026-09-04) but the Python port never executes them; say
  so explicitly to avoid future archaeology.
  ✅ documented in AGENTS.md (this batch).

Improvements already shipped this round (for the changelog):
- [x] Orchestrator narration persisted: siesta.sh tees stdout+stderr to
  `factory/pipeline.log` (9b45293). README/AGENTS updated accordingly.