---
name: issue-executor
description: Implement a pipeline issue with code and tests. Return CONSULT when stuck or PROXY_REQUEST when approval is needed; leave completion and commits to Python.
---

# Issue Executor

The configured worker implements one issue at a time. Follow the supplied
`incremental-implementation` and `test-driven-development` skills for
implementation and testing, subject to the pipeline handoff below.

## Runtime Contract

The worker has write, edit, read and bash tools for product work. Python
supplies the issue, KB summaries, standing principles and source context.
Use only skills and tools actually supplied; references do not install skills.

**Python owns completion records, checkpoints, recovery and Git commits.**
Leave product edits uncommitted. Do not stage or commit files, reset or clean
the repository, create completion nodes, or edit checkpoints/verdicts.
This applies during implementation, repair and review-fix calls. It overrides
generic advice to commit after each increment: Python first runs its tests,
then records completion and commits.

## Process

1. Read the issue, acceptance criteria, supplied context and relevant source.
   Use focused reads to fill gaps.
2. Follow TDD: write a failing behavior test, implement the smallest working
   change, then refactor with tests green.
3. Run relevant tests and regressions with the project's actual runner.
   Every issue needs executable passing tests, including scaffolding issues.
4. For unfamiliar APIs, inspect available project documentation and installed
   source. If a necessary fact cannot be established, consult; do not request
   an absent skill.
5. Report changed files, observed test results, significant decisions and
   remaining uncertainty. Leave source and tests ready for Python's checks.

## Stuck and Approval Protocols

When stuck or missing a necessary fact, return:

    CONSULT: <specific question>
    CONTEXT: <what was attempted and observed>
    CODE: <relevant source or actual error>

If a supplied skill asks for human approval, return:

    PROXY_REQUEST: <decision that needs approval>
    CONTEXT: <why it is needed and how it relates to the issue>

Put markers at line start, outside fences, and end the turn. Python routes
the request and provides feedback. After approval or guidance, implement and
test; approval alone is not completed work. Report any remaining blocker.

## Handoff

Provide a concise factual final report. Do not narrate tool-call JSON, ask
the absent human questions, or quote example markers as real requests.
Do not label the issue completed yourself.

Python runs the regression suite before writing the completion decision and
commit. Red or absent tests block the issue. Python archives and discards
blocked uncommitted work; leave that recovery to it. Per-issue learning runs
after successful completion is recorded.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll guess the missing fact" | Consult with the specific evidence gap. |
| "Tests can come later" | Each issue must leave executable passing tests. |
| "I should commit to save my work" | Python commits after its verification gate. |
| "The proxy approved, so I am done" | Implement and test the approved approach. |
| "I can mark the KB complete" | Completion is Python's evidence-backed decision. |

## Red Flags

- Claimed edits or test runs without actual tool execution
- Changing acceptance tests merely to hide failure
- Invoking absent skills or fabricating external evidence
- Staging, committing, restoring or deleting recovery evidence
- Editing bookkeeping to bypass verification gates

## Verification

- [ ] Acceptance criteria have an implementation and meaningful tests
- [ ] Reported test results were actually observed
- [ ] Product edits remain uncommitted for Python
- [ ] Decisions and unresolved concerns appear in the handoff
- [ ] Any consultation or approval request uses its exact protocol
