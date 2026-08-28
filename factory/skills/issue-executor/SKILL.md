---
name: issue-executor
description: Executes a single issue from the task list. Use when the factory pipeline assigns an issue to the worker model. Follows incremental-implementation and test-driven-development patterns. Outputs CONSULT: when stuck.
---

# Issue Executor

The worker model's playbook for executing a single issue. This skill extends `incremental-implementation` and `test-driven-development` with factory-specific orchestration: KB context loading, stuck detection, and git commits.

## When to Use

- The factory pipeline assigns an issue to execute
- NOT for: spec writing, planning, or review (those have their own skills)

## Process

### Step 1: Load Context

1. Read the issue description and acceptance criteria
2. Query the KB graph for relevant decisions and learnings:
   ```bash
   kb-manager.sh query kb/graph.json --summary-only
   ```
3. Activate `context-engineering` skill to pack the right context
4. If the issue uses a framework/library, activate `source-driven-development` to verify against docs

### Step 2: Implement

1. Follow `incremental-implementation` skill:
   - Thin vertical slices
   - One feature at a time
   - Safe defaults, no breaking changes
2. If building UI → activate `frontend-ui-engineering` skill
3. If building API → activate `api-and-interface-design` skill

### Step 3: Test

1. Follow `test-driven-development` skill:
   - Write failing test first (Red)
   - Implement to make it pass (Green)
   - Refactor (Refactor)
2. Run tests and verify they pass

### Step 4: Evaluate — Am I Stuck?

After each implementation attempt, self-assess:

**If you can continue:** proceed to Step 5.

**If you are stuck** (you don't know how to proceed, you've tried 2 approaches and neither worked, you're unsure about a design decision), output EXACTLY:

```
CONSULT: <your specific question for the consultant>
CONTEXT: <what you've tried so far>
CODE: <relevant code or error message>
```

Then STOP. The orchestrator will route this to the consultant model (GLM-5.2). Do NOT guess or proceed with low confidence.

### Step 5: Log Decision

1. Log any significant decision to the KB:
   ```bash
   kb-manager.sh append-node kb/graph.json "decision" "<one-line summary>" "<full reasoning>"
   ```
2. If a learning was discovered, log it:
   ```bash
   kb-manager.sh append-node kb/graph.json "learning" "<one-line summary>" "<full detail>"
   ```

### Step 6: Git Commit

1. Follow `git-workflow-and-versioning` skill:
   - Atomic commit scoped to this issue
   - Message format: `🔧 Issue #N: <short description>`
   ```bash
   git add -A
   git commit -m "🔧 Issue #N: <description>"
   ```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll figure it out as I code" | If you're unsure about the approach, CONSULT first. Guessing wastes a full implementation cycle. |
| "Tests are obvious, I'll add them after" | TDD is non-negotiable. Red-Green-Refactor. No exceptions. |
| "This decision is too small to log" | If it affects future issues, log it. KB exists to prevent repeating mistakes. |
| "I'll commit everything at the end" | Atomic commits per issue. If something breaks, you need to know which issue caused it. |
| "I think this works but haven't tested" | Untested code is not done. Run the tests. |

## Red Flags

- Writing more than 100 lines without a test
- Proceeding with an approach you're not confident about (should have CONSULTed)
- Committing multiple issues in one commit
- Not logging decisions to the KB
- Skipping KB context loading ("I know what to do")

## Verification

- [ ] Issue acceptance criteria are met
- [ ] Tests written and passing
- [ ] No regressions in existing tests
- [ ] Decision logged to KB graph
- [ ] Git commit is atomic and scoped to this issue
- [ ] If stuck: CONSULT output was generated with clear question, context, and code