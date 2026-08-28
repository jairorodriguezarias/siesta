---
name: consultant-protocol
description: Protocol for consulting the senior model (GLM-5.2) when the worker (Qwen 2.5) is stuck. Use when the worker outputs CONSULT:. Extends doubt-driven-development with cross-model handoff.
---

# Consultant Protocol

When the worker model (Qwen 2.5) gets stuck and outputs `CONSULT:`, this skill defines how the consultant model (GLM-5.2) receives the question, reasons about it, and returns a resolution.

## When to Use

- Worker outputs `CONSULT: <question>` with `CONTEXT:` and `CODE:`
- Worker has tried at least one approach and failed
- NOT for: simple questions the worker should know (rare exceptions)

## Process

### Step 1: Receive the Consultation

Parse the worker's output:

```
CONSULT: <question>
CONTEXT: <what was tried>
CODE: <relevant code or error>
```

### Step 2: Load KB Context

Query the KB for any prior decisions or learnings related to this issue:

```bash
kb-manager.sh query kb/graph.json --summary-only
```

The consultant gets:
- The worker's question and context
- Relevant KB summaries (progressive disclosure — summaries first)
- The issue's acceptance criteria

### Step 3: Adversarial Review

Follow `doubt-driven-development` skill:

1. **CLAIM** — What is the worker trying to do?
2. **EXTRACT** — What assumptions is the worker making?
3. **DOUBT** — Challenge each assumption:
   - Is the approach correct?
   - Is there a simpler way?
   - Is the worker stuck because of a wrong assumption or missing knowledge?
4. **RECONCILE** — Resolve the doubt with evidence
5. **STOP** — When confident, produce the answer

### Step 4: Produce Resolution

Output in this exact format:

```
RESOLUTION: <clear answer to the question>
APPROACH: <recommended approach, step by step>
RATIONALE: <why this approach, what was wrong with the worker's approach>
CODE: <if code changes are needed, provide them>
CONFIDENCE: high|medium|low
```

If the consultant cannot resolve with high or medium confidence:

```
ESCALATE: web search needed for <specific query>
```

### Step 5: Log to KB

Log the consultation:

```bash
kb-manager.sh append-node kb/graph.json "consultation" "<one-line summary>" "<question + answer + model>"
```

If the consultation resolved a blocker:

```bash
kb-manager.sh append-node kb/graph.json "decision" "<one-line summary>" "<full resolution>"
```

### Step 6: Return to Worker

The resolution is fed back to the worker model. The worker:
1. Reads the RESOLUTION and APPROACH
2. Implements the recommended approach
3. Continues with `issue-executor` skill from Step 2 (Implement)

## Escalation: Web Search Fallback

If the consultant outputs `ESCALATE: web search needed for <query>`:

1. The orchestrator runs a web search using `@ollama/pi-web-search`
2. Results are fed back to the consultant
3. Consultant re-evaluates with the search results
4. If still unresolved → log as blocker, skip issue

## Escalation: Blocker

If consultant + web search both fail:

1. Log to KB as blocker:
   ```bash
   kb-manager.sh append-node kb/graph.json "blocker" "<one-line summary>" "<full detail>"
   ```
2. Mark issue as "blocked" in issues.md
3. Skip to next issue
4. Continue pipeline

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I can figure this out without KB context" | The KB exists because past decisions matter. Always query it. |
| "The worker just needs a hint, I'll give a vague answer" | Be specific. Provide code. The worker needs actionable guidance, not philosophy. |
| "I'm not sure but let me guess" | If confidence is low, ESCALATE. Don't pass a guess to the worker as a resolution. |
| "This is too small to log" | Every consultation is valuable. Future issues may hit the same problem. |

## Red Flags

- Returning vague advice without code examples
- Not querying the KB before answering
- High confidence answer without evidence
- Not logging the consultation to KB
- Guessing instead of escalating when unsure

## Verification

- [ ] Worker's CONSULT was fully parsed (question, context, code)
- [ ] KB was queried for relevant context
- [ ] Resolution includes clear answer + approach + rationale
- [ ] If code changes needed, code is provided
- [ ] Confidence level is stated
- [ ] Consultation logged to KB graph
- [ ] If escalated, web search was performed and results fed back