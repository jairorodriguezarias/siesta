# Correctness and simplification audit — 2026-11-02

## Scope

Reviewed desktop launch/resume, process shutdown, HTTP boundaries, KB identity,
reference context, pipeline checkpoints, source selection and model routing.
Corrections target reproduced failures. This is not a proof that arbitrary
generated applications or every provider configuration will work.

## Confirmed findings and corrections

| Priority | Finding | Correction | Regression evidence |
|---|---|---|---|
| High | Resume discarded the selected directory and derived another path from the idea. Imported projects could launch a different project and load different model selections. | Carry the selected directory through the HTTP adapter and runner; use explicit CLI project selection when identity cannot be recovered from the original idea. | `test_resume_keeps_the_selected_project_directory`, `test_resume_uses_selected_directory_not_idea_slug`, `test_resume_reuses_routes_from_selected_directory`, `test_legacy_resume_without_idea_uses_committed_identity` |
| High | Two KB nodes could receive the same timestamp/random identifier. Reads and updates then targeted the first node with that ID. | Check existing IDs and advance the suffix on collision, preserving the public ID format. | `test_colliding_ids_keep_nodes_and_edges_distinct` forces identical time and random values. |
| Medium | A legacy reference title larger than the context budget made the truncation loop run forever after its body became empty. | Shorten the largest field until the serialized reference fits; retain explicit truncation evidence. | `test_oversized_legacy_title_cannot_hang_context` reproduces the hang in a subprocess with a deadline. |
| Medium | Valid JSON with a non-object root in the status file raised an exception during Activity polling. | Treat unsupported state roots as missing status while retaining the real process outcome. | `test_non_object_status_does_not_break_activity` covers arrays, null, numbers and strings. |
| Medium | A process exiting between the graceful-stop timeout and the forced signal caused Stop to fail. | Share shutdown logic between Stop and desktop close; tolerate an already-exited process at either signal. | `test_stop_handles_process_exiting_before_forced_kill` forces the race. |

The KB identifier correction prevents new collisions; it does not rewrite old
graphs whose IDs already collide. Graph writes still require serialized writers.
Imported projects still need the committed identity and artifacts required by
the CLI. Canonical unfinished interviews retain their existing resume route.

## Simplification

- One termination routine now owns graceful and forced process shutdown.
- Launch determines the project directory once and shares it with model routing.
- Reference truncation uses one rule for both title and body.

The larger orchestration modules (`phases.py` and `reviews.py`) remain candidates
for a separate extraction by responsibility. This audit does not change their
review protocols or recovery boundaries solely to reduce file size.

## Validation

| Check | Result |
|---|---|
| Focused KB, reference, desktop process and HTTP suites | 61 tests passed |
| `python -B -m unittest discover -s tests -q` from `factory/` | 502 tests passed in 166.672 seconds |
| `node --test factory/tests/test_snake.mjs` | 5 tests passed |
| `node factory/tests/web_smoke.mjs` | Passed; no browser errors, including mobile, resume, KB and Stop |
| `git diff --check` | Passed |

The first browser run exposed a stale method signature in its test fixture;
the fixture was updated to carry the selected project and the browser suite
passed on rerun. Focused tests reproduce the production defects above before
their respective fixes. Live model evaluations are outside this audit; the
provider-independent tests use simulated Pi responses.
