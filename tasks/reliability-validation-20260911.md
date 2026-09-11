# Reliability fixes and local validation — 2026-09-11

The six reliability corrections are complete on `fix/reliability-local-runs`,
based on `86687bc`. Implementation: `2907a87`; additional recovery regressions:
`e3d4878`. The final Siesta suite passes **215 tests**, and all four local
projects finish with exit 0, checkpoint `complete`, and `VERIFY_PASSED`.
Independent validation passes **62 generated tests and 14 CLI contract checks**.

## Corrected behavior

- Verification always runs the mechanical suite. Red or absent tests cannot
  pass through a model approval; explicit model failure and failed runtime
  smoke checks veto success. Every completed issue also needs passing tests.
- Consultation, proxy and diagnosis retries pass through the same bounded
  validation. Empty answers and unresolved requests remain blocked; a short
  valid protocol request after a degenerate answer reaches its proper handler.
- Review fixes run with write tools and receive a fresh review. Both
  `REVIEW_PASSED` and explicit proxy approval are required to advance.
- The interview deadline covers an open stdout pipe and kills the child
  process group while preserving partial text. Failed provider exits cannot
  supply usable model answers.
- Recovery restores both index and working tree from HEAD, preserves KB and
  ignored evidence, and saves binary patches plus untracked files under
  `.git/siesta-recovery/`. Unchanged tracked files are not archived. A second
  failed regression repair is recovered before the terminal halt commit.
- Resume retries pending issues even after later or legacy complete
  checkpoints, invalidates downstream review/verification, and preserves
  completed issue idempotency. Incomplete projects exit 1.

## Validation

The final factory suite ran on CPython 3.12.3 with pytest 9.1.1:
**215 tests passed in 70.659 seconds**, with no ResourceWarning in the log.
[Full suite log](../.runtime/reliability-tests.log).

The existing GUI caveat test initially failed because this interpreter lacks
Tkinter. Its fixture now imports Tk lazily: the real sleeping subprocess and
GUI source detection are still tested without requiring an installed GUI toolkit.
The obsolete test expecting a model approval to override red tests was updated.

Real Git repositories and subprocesses exercise failure, restoration, review,
and resume paths. New review findings were reproduced red before being fixed.
A separate reviewer approved correctness, readability, architecture, security
and performance after the fixes; no required findings remain.

The persistent environment is `.runtime/reliability-venv/`. Reproduce from
the repository root, activating it so generated subprocess tests find Python:

```bash
uv venv --python python3 .runtime/reliability-venv
uv pip install --python .runtime/reliability-venv/bin/python pytest==9.1.1
source .runtime/reliability-venv/bin/activate
cd factory
python -B -m unittest discover -s tests -v
```

## Local model runs

All roles used the existing `nvidia/Qwen3.6-35B-A3B-NVFP4` server at
`http://127.0.0.1:8000/v1`, through the isolated `local-vllm` pi profile.
The served model identity and 262144-token context were checked against the
pi catalog. A real pi probe successfully wrote a file, ran its assertion, and
read it back using native tools.
[Provider identity](../.runtime/local-validation-20260911/provider-identity.json),
[tool events](../.runtime/local-validation-20260911/tool-probe.jsonl).

| Project | Completed issues | Product tests | Independent cases | Recorded duration |
|---|---:|---:|---:|---:|
| [Caesar](../.runtime/local-validation-20260911/caesar/result.json) | 5/5 | 15 | 4 | 251.65 s |
| [Wordcount](../.runtime/local-validation-20260911/wordcount/result.json) | 3/3 | 13 | 2 | 296.30 s |
| [Temperature converter](../.runtime/local-validation-20260911/tempconv/result.json) | 3/3 | 24 | 5 | 510.45 s |
| [Dedupe](../.runtime/local-validation-20260911/dedupe/result.json) | 5/5 | 10 | 3 | 409.79 s for resume |

The independent checks cover exact output, empty input, Unicode, negative
shifts, invalid arguments, numeric/unit validation, duplicate order, blank
lines, spaces and case. All products were rechecked in the persistent
environment. [Final checks and pipeline source hashes](../.runtime/local-validation-20260911/final-product-checks.json).

The first three runs predate the final recovery edge-case fixes; dedupe resumed
with those fixes. Generated products were not manually implemented or repaired.
The main routing configuration remains the documented cloud configuration;
local routing, KB and learner skill changes belong to this isolated profile.

## Retained failures and limits

Dedupe's first attempt failed before issue 4 because its temporary uv
interpreter disappeared. With a persistent interpreter it skipped completed
issues 1–3, restored residue, finished issues 4–5, and repeated review and
verification. Its historical `Pipeline failed` KB node remains; no issues
remain blocked. [Initial failure](../.runtime/local-validation-20260911/dedupe/pipeline.initial-failed.log),
[resumed run](../.runtime/local-validation-20260911/dedupe/pipeline.log).

The first external recheck omitted the environment's bin directory from PATH:
wordcount's CLI checks passed, but six generated tests could not launch
`python`. Activating the same environment for child processes fixed the
checker without changing the product.
[Preserved failed check](../.runtime/local-validation-20260911/product-checks-before-path-fix.json).

An earlier Caesar attempt under `factory/projects/reliability-20260910-caesar`
used cloud routing and failed DNS; it is excluded from these local results.

Dedupe's model QA answer was repetitive and omitted a verdict marker. Its
persisted pass comes from actual runtime and regression checks, not that
narration. Its project-level learning phase logged zero new learnings; this run
does not demonstrate useful learning for every project.

These results cover small Python CLIs, not GUI visibility, other stacks, or
universal autonomous reliability. Raw evidence and runnable validation drivers
are retained locally under `.runtime/local-validation-20260911/` and ignored
by Git. No merge, push, or deployment is part of this task.
