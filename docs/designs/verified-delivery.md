# Verified delivery

Status: implemented

Siesta should reject unclear designs before spending time on implementation,
and show which requirements have evidence when a run finishes. Keep the Python
orchestrator, explicit model routing and existing recovery protocol.

## Capabilities and order

| Capability | Acceptance | Depends on |
| --- | --- | --- |
| Process reliability | Preserve failed output, drain both pipes, enforce the deadline and reap Pi before interpreting its exit status | — |
| Independent design review | Two fresh, tool-free reviews see only intent, spec and plan; either rejection blocks implementation | Process reliability |
| Requirement evidence | Stable acceptance IDs map to existing tests and source; missing evidence, drift or failed mechanical tests veto completion | Design review |
| Reproducible evaluation | Small real-model cases record outcomes, elapsed time, calls and available usage/cost without invented measurements | Requirement evidence |
| Repository presentation | Clear README, original SVG artwork, linked guides, contribution instructions and offline CI | All |

## Contracts

- Specs use acceptance bullets `- R1: ...`, with unique IDs. Legacy specs can
  use unnumbered bullets under an acceptance/success-criteria heading.
- Reviewers use new ephemeral Pi calls with context-file, extension and
  implicit skill discovery disabled. No conversation, KB or learning history
  enters their prompts. This is context isolation, not an OS security sandbox.
- Review checks comprehension, simplicity and implementation readiness
  independently. Python verifies criterion-to-issue/test mappings and backward
  dependencies. It can apply up to two validated, committed document repairs
  without changing acceptance criteria or completed issues, then reviews the
  new version. Cached approval is bound to exact documents and model routes.
- Final evidence review receives requirements, source and current test output.
  It must map every requirement to existing file references and classify it as
  supported, missing or contradicted. Python validates the report, reruns the
  suite and owns the final verdict. Model judgments are identified as such.
- Reports and metrics are local evidence, excluded from source prompts and
  product commits. Completed legacy runs remain idempotent. Active legacy runs
  must pass the new gates before completion.
- Tests cover rejection, malformed replies, missing requirements/evidence,
  changed designs, isolation flags, resume and real subprocess failures.
- Benchmark fixtures assert output independently of generated tests. No fixed
  latency, success-rate or cost promises; unavailable usage/cost stays unknown.

## Scope

Use the standard library for the runtime. Simplify duplicate lifecycle logic
and completion checks as they are touched. Keep the CLI and existing phase
numbers; design review belongs between planning and execution. Do not add a
web UI, scheduler, agent framework or automatic model selection.

GitHub presentation takes inspiration from EGM's clarity and navigation, with
original Siesta artwork and honest validation claims. All documentation is in
English. Public publishing is separate from preparing and validating changes.
