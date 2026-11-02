# Agent and model-routing evaluation · 2 November 2026

This record covers the I17 live checks of the agent-review pipeline with
cloud, local and mixed Ollama routes. Each run used an isolated factory and
the same `sum` case: build `sum_cli.py`, then check addition, negative inputs
and invalid input with an external CLI checker. The checks do not trust the
generated tests. Results are individual observations, not a success-rate
estimate.

## Environment and routes

- Python 3.11.15, Pi 0.87.1, Linux aarch64. Case deadline: 900 seconds for
  local and mixed; each Pi call was limited to 180 seconds.
- Temporary Pi profiles under ignored `.runtime/` registered exact Ollama IDs.
  Credentials remained in the server. The default Pi profile alone registered
  `glm-5.3-flash:cloud`.
- Explicit compatibility checks confirmed text and native write tools for
  `glm-5.3-flash:cloud`, `glm-5.2:cloud`, `gemma4:31b-cloud` and
  `qwen3.8:latest`. `qwen2.5-coder:32b` answered text but failed the native
  write test, so it was not used as a worker.
- The mixed run's Pi profile declared the local model's 262144-token served
  window and 16384 maximum output tokens. The local-only run used an earlier
  4096-token declaration while Ollama served 262144; this mismatch limits
  interpretation of that run.

## Runs

| Route | Planner / consultant | Worker | Pipeline | External checks | Calls | Wall time |
| --- | --- | --- | --- | --- | ---: | ---: |
| Cloud v3 | `glm-5.2:cloud` | `gemma4:31b-cloud` | Blocked at final quality review | 3/3 passed | 13 | 61.979 s |
| Cloud v4 | `glm-5.2:cloud`; quality reviewer `gemma4:31b-cloud` | `gemma4:31b-cloud` | Blocked at issue review | CLI removed during recovery | 13 | 61.004 s |
| Local | `qwen3.8:latest` | `qwen3.8:latest` | Blocked: design reviewer timed out twice | CLI absent | 6 | 821.362 s |
| Mixed | `glm-5.2:cloud` | `qwen3.8:latest` | Blocked: worker timeouts, then final review lacked context for retry | CLI absent | 9 | 379.048 s |

Cloud v3 generated a CLI that passed all three independent checks. Its final
quality reviewer twice returned JSON inside a Markdown code fence; the strict
review parser correctly refused approval. Cloud v4's issue reviewer reported
defects, and subsequent fenced JSON prevented approval. Recovery preserved the
blocked state and removed unverified product files. Earlier cloud attempts
stopped at design validation because the parser rejected valid bold Markdown
labels for test strategy and dependencies. That parser was corrected with a
regression test before v3. No cloud run in this table completed the full
pipeline, even where the CLI checks passed.

In the mixed run the local worker exhausted two 180-second calls. Issue #1 was
blocked, and the final reviewer could not receive additional source context
for its retry. The strict gate stopped the run. No generated CLI survived the
blocked-issue recovery, so the external checks could not execute.

The local-only run reached design review, where the comprehension reviewer
timed out on both allowed calls. It used an earlier candidate source hash,
`dd2f78132cdd0e5c63fae3eeda5fd51df5c92e2c96b97868abdff6ed854006d1`,
before the Markdown-label parser correction. Its failure was a model timeout,
not that parser check. The local route therefore has compatibility evidence
for text and native tools but no successful end-to-end product evidence.

The copied pipeline source SHA-256 for cloud v3 and v4 was
`d82bc6f80221cb4ff0c36ad3d1f849dd871a091da21693853784472523117faf`;
the mixed run used the same source hash.
The isolated `results.json`, call records, console logs and generated projects
remain in ignored `.runtime/evaluation-siesta-agents-*` directories. The
earlier [two-case cloud evaluation](2026-11-02.md) completed with a prior
pipeline revision; it is not evidence that this final revision passes.

Token use and cost are unknown because Pi's text interface does not expose
reliable totals. These runs do not cover larger applications or performance
across a model population.
