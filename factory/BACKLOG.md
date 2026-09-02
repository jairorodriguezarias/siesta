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
- [ ] #3 Proxy gate fail-open: anything ≠ NEEDS_REVISION counts as approval
  (phases.py:537). Approves helpless narrations. Should require an explicit
  APPROVED marker.
- [ ] #4 `_detect_runnable` misses `python -m <pkg>` (package with
  `__main__.py`).
- [x] #5 Retro `issues.md` template hardcoded for the previous (HTML) project.
  Fixed.
- [ ] #6 Phase 6 commits "Project verified" even when verdict = VERIFY_FAILED
  (__main__.py:169-171); resume path also hardcodes VERIFY_PASSED
  (__main__.py:161). Tie the decision node + commit message to the actual
  verdict.
- [ ] #7 Generated projects commit `.DS_Store`/`__pycache__`/`.pipeline-checkpoint`
  (`git add -A`, no .gitignore). Write a standard .gitignore at project init.
- [ ] #8 Learners emit 0 parseable learnings even with `--no-tools` (root KB has
  only failure nodes). Root cause: prompt format vs `learn.py` parser mismatch.
- [ ] #9 `execute()` is not per-issue idempotent (found in code walkthrough,
  2026-08-31). A crash mid-phase-3 re-runs ALL issues on `--resume`, ignoring the
  3 completion records already on disk (KB "Issue #N completed" decision node,
  `🔧 Issue #N` git commit, `issue_N_output.txt`); in-memory `fails`/`history`/
  `blocked` (phases.py:380) are lost. Fix sketch: skip issues that already have a
  completion node in `kb.query(type_="decision")` (~3 lines in the execute loop).
  Nice emergent behavior: blocked issues lack the node, so they naturally retry.
- [ ] #10 `run_pi()` has no timeout (found in code walkthrough, 2026-08-31).
  A hung `pi`/Ollama call freezes the pipeline forever; `stop.md` can't help
  because it is only checked between issues. Add `timeout=` + a retry policy.
  Same family as #2: the pipeline assumes calls terminate and tell the truth.
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
- [ ] #16 Review "fix" pass is a no-op (found in code walkthrough, 2026-09-02):
  when the proxy requests revision, the pipeline runs the worker with
  "Fix the issues now" but `tools="no"` (phases.py:539-543) — the worker
  cannot write files, so "fixes" land in `review_fixes_output.txt` and are
  NEVER applied. `ok("Review complete")` follows unconditionally. Invalidates
  phase 4's purpose. Fix sketch: give this pass write tools (like the execute
  phase), and re-commit after it.
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
- [ ] #18 (minor) Review gate uses a raw substring check `"NEEDS_REVISION" in
  proxy_out` (phases.py:537) instead of an anchored marker like `text.REJECTED`
  — accidental mentions trigger revision requests. Make proxy gates use the
  same anchored-marker style as the rest of the protocol.
- [ ] #19 Runtime smoke is HTTP-only and punishes working CLIs (found in code
  walkthrough, 2026-09-02): `runtime_smoke()` probes with `urlopen` — a CLI
  that starts, prints and exits cleanly (exit 0) is reported as
  `FAILED: process exited with code 0` (phases.py:599-600). Any detected CLI
  project is misjudged as broken. Combined with #4 (narrow detection), only
  web projects get a meaningful smoke. Fix sketch: for non-web entry points,
  treat "exited 0 within N seconds" as PASSED and "non-zero exit / crash" as
  FAILED; keep the HTTP probe only for `npm start`/server-ish projects.
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

- [ ] run_pi() concatenates stdout+stderr into the parsed text. Provider noise in
  stderr can corrupt marker parsing. Consider tagging/filtering stderr before
  parse, or logging stderr separately from the artifact. Evidence: pomodoro
  `verify_output.txt` contains `Warning: Model "qwen2.5-coder:latest" not
  found for provider "ollama". Using custom model id.` — pi stderr noise inside
  the parsed artifact; it also flags that calls may not run the intended model.
- [ ] `Graph` reads the whole file at init and rewrites it whole on every node()
  — two instances over the same path in one process lose each other's writes.
  Latent (each graph has one owner today); safe until someone refactors.
- [ ] `Graph.node()` validates types against schema.json but `edge()` validates
  nothing — any from/to/kind passes.

- [ ] run_pi() concatenates stdout+stderr into the parsed text. Provider noise in
  stderr can corrupt marker parsing. Consider tagging/filtering stderr before
  parse, or logging stderr separately from the artifact.
- [ ] Marker parsers (`REVIEW_*`, `VERIFY_*`, `CONSULT`, `PROXY`) accept markers
  inside fenced code blocks the model quotes as examples (false positives) —
  fence content sits at column 0 so the `^` anchor doesn't help. `spec_doc()`
  already solves this for spec/plan by rejecting live fences; reuse that
  approach (ignore code-fence regions before matching).