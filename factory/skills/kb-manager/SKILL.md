---
name: kb-manager
description: Manages the JSON-based knowledge graph with progressive disclosure. Use when reading or writing decisions, blockers, learnings, or consultations to the KB. Provides query, append, and link operations.
---

# KB Manager

Manages the file-based JSON knowledge graph. Nodes store typed information (decisions, blockers, learnings, consultations) with summary + detail for progressive disclosure. Edges store typed relationships between nodes.

## When to Use

- Before executing an issue: query relevant KB context
- After making a decision: log it to KB
- After resolving a blocker: log resolution to KB
- After learning something: log it to KB
- NOT for: trivial changes that don't affect future work

## KB Structure

```json
{
  "nodes": [
    {
      "id": "n1234_5678",
      "type": "decision|blocker|learning|consultation|spec|issue",
      "summary": "One-line summary (loaded first)",
      "detail": "Full reasoning (loaded on drill-down)",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "edges": [
    {
      "from": "n1234_5678",
      "to": "n5678_9012",
      "type": "applied_to|caused_by|resolved_by|depends_on|parent_of|consulted_for|learned_from",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

## Progressive Disclosure

**Level 1 — Summary only** (default, cheap):
```bash
kb-manager.sh query kb/graph.json --summary-only
# Returns: [{id, type, summary}] — minimal tokens
```

**Level 2 — Full node** (on demand, when an issue needs detail):
```bash
kb-manager.sh get-node kb/graph.json n1234_5678
# Returns: full node with detail field
```

**Level 3 — Filtered by type** (when you need all decisions, or all blockers):
```bash
kb-manager.sh query kb/graph.json --type decision --summary-only
```

## Operations

### Query (read)
```bash
# All summaries (cheapest)
kb-manager.sh query kb/graph.json --summary-only

# All decisions only
kb-manager.sh query kb/graph.json --type decision --summary-only

# Full detail for a specific node
kb-manager.sh get-node kb/graph.json n1234_5678

# List everything (quick overview)
kb-manager.sh list-all kb/graph.json
```

### Append Node (write)
```bash
# Log a decision
kb-manager.sh append-node kb/graph.json "decision" \
  "Used argparse for CLI parsing" \
  "Qwen chose argparse over click for zero dependencies. Click requires extra pip install."

# Log a blocker
kb-manager.sh append-node kb/graph.json "blocker" \
  "Timer drift on long sessions" \
  "time.time() drifts. Fixed by using time.monotonic(). Suggested by the consultant."

# Log a learning
kb-manager.sh append-node kb/graph.json "learning" \
  "Always use monotonic for timers" \
  "time.time() is affected by system clock changes. time.monotonic() is immune."

# Log a consultation
kb-manager.sh append-node kb/graph.json "consultation" \
  "Consultant advised on timer drift" \
  "Worker asked about timer drift. Consultant recommended time.monotonic(). Confidence: high."
```

### Append Edge (link)
```bash
# Decision was applied to an issue
kb-manager.sh append-edge kb/graph.json n1234_5678 n9012_3456 applied_to

# Blocker was resolved by a consultation
kb-manager.sh append-edge kb/graph.json n3456_7890 n5678_9012 resolved_by

# Learning was learned from a blocker
kb-manager.sh append-edge kb/graph.json n5678_9012 n3456_7890 learned_from
```

### Initialize (new project)
```bash
kb-manager.sh init-project kb/graph.json
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll remember this decision" | You won't. The KB is the memory. Log it. |
| "Detail is too long to write" | Summary is enough for Level 1. Detail can be long — it loads on demand. |
| "I don't need to query the KB, I know the context" | Past decisions affect current work. Always query summaries first. |
| "This is too small to log" | If a future issue could benefit, log it. Small decisions compound. |

## Red Flags

- Writing detail without a summary (summary is the progressive disclosure entry point)
- Creating nodes without edges (orphan nodes are hard to discover)
- Loading full detail when summaries would suffice (wastes context tokens)
- Not initializing a fresh KB per project (cross-project contamination)

## Verification

- [ ] Every decision has both summary and detail
- [ ] Blockers have resolution edges to what resolved them
- [ ] Consultations are linked to the issue they were for
- [ ] Summaries are one line, under 100 characters
- [ ] Queries start with --summary-only before drilling into detail