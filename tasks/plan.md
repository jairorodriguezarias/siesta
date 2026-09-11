# Reliability fixes and four local model runs

Fix the six reproduced defects on GitHub revision `86687bc`, then run four
complete projects through the corrected pipeline using only local inference.
The previous local stash is a backup, not the implementation baseline.

## Approach

1. Require a passing mechanical suite at verification, regardless of model markers.
2. Validate every execution retry; unresolved requests and empty answers never complete issues.
3. Re-review fixes and require explicit review and proxy approval before advancing.
4. Enforce the interview deadline while stdout is open; preserve partial evidence and reap children.
5. Restore blocked product work from HEAD, including staged and untracked changes;
   preserve KB, ignored evidence, and a recovery backup before cleanup.
6. Resume pending issues despite later checkpoints and invalidate downstream review/verification.
7. Verify the full suite, review the diff, and run four distinct small Python projects
   with actual local model calls. Independently test each generated project's contract.

## Verification

Use unittest with pytest available for generated regression suites. Add failing
reproductions before each fix, using real temporary Git repos and subprocesses.
Local run evidence must include the routing configuration, provider/model identity,
pipeline exit status, checkpoint, issue outcomes, final verification and independent
product checks. A failed real run stays failed in the report; no simulated model
output or manual implementation counts as a successful autonomous run.

## Risks

Local inference shares a busy GPU with existing services. Inspect capacity and
available endpoints before loading anything; avoid disrupting unrelated workloads.
Model tool support and served context must be tested through pi before the runs.
Keep runtime credentials and transcripts out of commits. Work on a short-lived
branch; merging or deploying is outside this task.
