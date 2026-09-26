# Safe repository iterations

## Objective and scope

Continue developing a Siesta-generated Git repository without confusing old
completion evidence with new work. Preserve human edits, retain recoverable
worker failures, and require successful commits and current verification.
The implementation uses Python's standard library and the existing Pi routes.
Importing arbitrary repositories without Siesta's intent/spec/plan is outside
this change; `--project` targets an existing Siesta project explicitly.

## Capability map and implementation order

| Module | Responsibility | Depends on |
|---|---|---|
| prompt-inputs | Git-aware, bounded source selection without private/vendor inputs | — |
| process-lifetime | Kill timed-out Pi process groups and preserve partial evidence | — |
| repository-state | Strict commits, committed completion ledger, product fingerprints, human edits | prompt-inputs |
| iterations | Explicit project selection and new spec/plan amendments | repository-state |

Implement and validate the boundaries first, then repository state, then the
iteration CLI. Keep model prompts in their owning phase/module and Git/state
operations in a focused module. Do not grow the already large phase module
with another independent state machine.

## Commands and behavior

```bash
# Existing behavior: create or resume the original idea.
./factory/bin/siesta.sh --auto 'Build a Python answer CLI with tests'

# Resume an existing Siesta project without repeating its original idea.
./factory/bin/siesta.sh --project factory/projects/PROJECT --resume

# Plan and execute an additional request in the same Git repository.
./factory/bin/siesta.sh --project factory/projects/PROJECT --iterate 'Add JSON output and tests'

# Explicitly commit local edits before resuming or planning an iteration.
./factory/bin/siesta.sh --project factory/projects/PROJECT --adopt-changes --resume
```

An iteration updates the specification and appends new, uniquely numbered
issues; it preserves existing issue bodies, original intent and Git history.
The latest identical iteration request resumes its existing work. A different
request requires finishing the active work first. Spec/plan generation is
bounded and cannot execute file/shell tools. Invalid output or failed plan
commits leave the existing plan recoverable and cannot start implementation.

## Acceptance criteria

1. Unchanged completed projects perform no duplicate implementation, review,
   completion commits or learning. A changed product invalidates prior review
   and verification, including changes committed outside Siesta.
2. Verification evidence identifies the product content, including requirements
   and executable modes, excluding KB bookkeeping and ignored run artifacts.
   Legacy projects without fingerprints are checked again before success.
3. Every recorded completed issue corresponds to a successful commit. A commit
   failure raises an error, preserves edits and cannot leave a false completion
   node/checkpoint. Completion/failure records themselves must also commit.
4. Completed issue requirements are immutable: edits/removals are rejected with
   guidance to add a new issue or use `--iterate`. Legacy completion records
   are reconciled with their committed plan. Duplicate issue numbers fail.
5. Unknown dirty product files are preserved and block startup/issue execution.
   `--adopt-changes` explicitly commits them. Cleanup is reserved for known
   failed-worker work during the active run and retains recovery archives.
6. Ignored/private/runtime/vendor files and symlinks are excluded from gathered
   model context. Legitimate untracked product files remain visible. This is
   prompt filtering, not a sandbox for the worker's explicitly enabled tools.
7. A timed-out Pi call terminates its entire process group before returning,
   retains partial stdout/stderr as evidence and returns no usable answer.
   Failed interactive calls cannot authorize an intent from partial output.
8. `--project` validates an actual Siesta Git root. Invalid targets, a different
   colliding idea and rejected local edits do not mutate another project's KB.
9. Iteration tests prove old behavior and history survive, new behavior is
   implemented, failed work resumes, and repeat requests do not duplicate work.

## Tests, style and boundaries

Tests live in `factory/tests/` and follow the existing `unittest` conventions:
descriptive `test_...` methods, temporary Git repositories, real subprocesses
and pytest suites, and fake Pi only at the model boundary. For example:

```python
self.assertNotEqual(result.returncode, 0)
self.assertEqual(product.read_bytes(), before)
self.assertNotIn("Issue #2 completed", decisions)
```

Run focused tests after each increment and the full suite before delivery:

```bash
cd factory
python -B -m unittest discover -s tests -v
```

Always preserve local user data and record meaningful failure evidence. Use
the existing standard-library stack, relative paths and explicit model routes.
Do not publish, push, rewrite Git history, change model defaults or repair real
generated projects as part of implementing this feature. Update README,
AGENTS and test documentation when the contracts change.
