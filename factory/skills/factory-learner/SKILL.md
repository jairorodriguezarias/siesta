---
name: factory-learner
description: Learns after EACH issue execution, not just at project end. Qwen 2.5 governs this micro-learning loop. Analyzes what happened during the issue — blockers, consultations, proxy decisions, successes — and improves factory skills immediately. Use after every issue is resolved.
---

# Factory Learner

After EVERY issue is executed, Qwen 2.5 analyzes what happened and learns from it. This is micro-learning: granular, immediate, and actionable. The factory gets smarter after each issue, not just after each project.

## When to Use

- After EVERY issue is executed (post-issue hook)
- After the full project completes (project-level summary)
- NOT during issue execution — this is post-execution reflection

## Two Levels

### Level 1: Per-Issue Learning (after each issue)

Runs immediately after the issue's post hooks (the per-issue learning step in `pipeline/learn.py`). Qwen analyzes:

1. **Did I get stuck? (CONSULT)**
   - What was the question?
   - What did the consultant answer?
   - Could the `issue-executor` skill have prevented this?
   - → If yes: append to `issue-executor` Red Flags or Process

2. **Was I rejected by the proxy? (PROXY_REQUEST → REJECTED)**
   - What did I propose?
   - Why did the proxy reject it?
   - What should I do differently next time?
   - → Append to `issue-executor` Rationalizations table

3. **What decision did I make?**
   - Was it a good decision?
   - Is it a pattern that could repeat?
   - → Log to global KB as learning

4. **Did anything go well that's worth preserving?**
   - Efficient approach that worked
   - Clean pattern that should be reused
   - → Log to global KB as best practice

5. **Was there a new pattern not covered by any skill?**
   - Something no skill addresses
   - → Create new factory skill (only if pattern is likely to repeat)

### Level 2: Project-End Learning (after all issues done)

Runs once at the end. Qwen analyzes the full project:

1. Which issues had blockers? Were they related?
2. Which consultations were most valuable?
3. Were there cross-issue patterns?
4. Should any factory skill be restructured?
5. Summary of all learnings → global KB

## Process — Per-Issue Learning

### Step 1: Gather Issue Context

After an issue is executed, collect:

```bash
# The issue that was just executed
ISSUE_TEXT=<from issues.md>

# Was there a consultation?
CONSULT_OUTPUT=<from consult_N_output.txt>

# Was there a proxy decision?
PROXY_OUTPUT=<from proxy_N_output.txt>

# Was there a blocker?
BLOCKER=<from blocker log in KB>

# The issue execution output
ISSUE_OUTPUT=<from issue_N_output.txt>

# Was there a retry?
RETRY_OUTPUT=<from issue_N_retry_output.txt>
```

### Step 2: Analyze

Qwen analyzes the issue with these questions:

```
ANALYSIS:
  Issue: #N
  Had consultation: yes/no
  Had proxy rejection: yes/no
  Had retry: yes/no
  Had blocker: yes/no
  
  What went wrong:
    - <specific thing that went wrong>
  
  Root cause:
    - <why it went wrong>
  
  What the skill should have covered:
    - <what guidance was missing>
  
  What I should do differently next time:
    - <actionable change>
  
  What went well:
    - <thing that worked and should be repeated>
  
  Pattern classification:
    - SKILL_IMPROVEMENT: <which skill> <what to add>
    - NEW_SKILL: <name> <what it covers> (only if truly novel)
    - LEARNING: <summary> <detail> (log to global KB)
    - NO_ACTION: <nothing to learn> (rare — almost always something)
```

### Step 3: Act

#### If SKILL_IMPROVEMENT identified:

Append to the factory skill. The format depends on where it fits:

**Red Flags** (something went wrong):
```markdown
- <pattern that caused the problem> → <what to do instead>
```

**Common Rationalizations** (excuse the worker made):
```markdown
| "<excuse>" | "<why it's wrong>" |
```

**Process** (missing step):
```markdown
N. <new step that should be followed>
```

**Verification** (missing check):
```markdown
- [ ] <new check to perform>
```

#### If NEW_SKILL identified:

Only if the pattern is novel AND likely to repeat across projects. Create:

```
factory/skills/<new-skill-name>/SKILL.md
```

#### If LEARNING identified:

Log to global KB:
```bash
python3 -m pipeline.kb append-node factory/kb/global-graph.json "learning" \
  "<one-line summary>" \
  "<full detail: which issue, what happened, what was learned>"
```

### Step 4: Update Global KB

Always log to global KB so future issues and projects benefit:

```bash
# If there was a blocker
python3 -m pipeline.kb append-node factory/kb/global-graph.json "blocker" \
  "Issue #N: <blocker summary>" \
  "<what caused it, how it was resolved>"

# If there was a consultation worth preserving
python3 -m pipeline.kb append-node factory/kb/global-graph.json "consultation" \
  "Issue #N: <consultation summary>" \
  "<question + answer + model>"

# If there was a learning
python3 -m pipeline.kb append-node factory/kb/global-graph.json "learning" \
  "<learning summary>" \
  "<full detail>"
```

### Step 5: Report

```
ISSUE_LEARNING #N:
  Stuck: yes/no
  Consulted: yes/no
  Rejected by proxy: yes/no
  Retried: yes/no
  Blocked: yes/no
  
  Learnings:
    - <what was learned>
  
  Skill improvements:
    - <skill>: <what was added>
  
  Global KB: +N nodes
```

## Process — Project-End Learning

After all issues are done, run once:

1. Read ALL issue learnings from global KB
2. Identify cross-issue patterns
3. Check if any factory skill needs restructuring
4. Create a project summary learning
5. Log to global KB

```
PROJECT_LEARNING:
  Issues executed: N
  Total blockers: N
  Total consultations: N
  Total proxy decisions: N
  
  Cross-issue patterns:
    - <pattern that appeared in multiple issues>
  
  Skills improved during project:
    - <skill>: <improvements made>
  
  Skills created during project:
    - <skill>: <what it covers>
  
  Global KB: +N nodes total
```

## Rules

1. **Always learn after every issue** — even "simple" issues produce learnings
2. **Be specific** — "add test for edge case X" not "improve testing"
3. **Don't modify addyosmani skills** — only factory skills
4. **Only create new skills for REPEATED patterns** — not one-offs
5. **Log to global KB immediately** — don't batch
6. **The learning is about the PROCESS, not the code** — the code is in git, the learning is about HOW we made it

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "This issue was simple, nothing to learn" | Even simple issues have decisions. What did you decide and why? |
| "I'll learn at the end of the project" | By then you've forgotten the specifics. Learn NOW while it's fresh. |
| "I don't want to modify the skill for one issue" | If it happened once, it can happen again. Add it as a Red Flag. |
| "Creating a new skill is overkill" | If the pattern is novel and repeatable, it's not overkill. It's how the factory evolves. |
| "The learning is too small to log" | Small learnings compound. Log everything. |

## Red Flags

- Skipping the learning step after an issue
- Vague learnings ("improve testing" instead of "add edge case test for empty input")
- Modifying addyosmani skills
- Not logging to global KB
- Creating a skill for a one-off pattern
- Batching learnings instead of doing them per-issue
- Learning about code quality instead of process quality

## Verification

Per-issue:
- [ ] Issue context was gathered (output, consult, proxy, retry, blocker)
- [ ] Analysis was specific (not vague)
- [ ] If skill improvement identified, it was applied
- [ ] Learning was logged to global KB
- [ ] Report was output

Per-project:
- [ ] Cross-issue patterns were identified
- [ ] All factory skill improvements were applied
- [ ] Project summary was logged to global KB