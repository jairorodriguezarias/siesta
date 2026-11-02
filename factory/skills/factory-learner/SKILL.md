---
name: factory-learner
description: Analyze supplied issue or project evidence and return structured learnings and proposed factory skill updates for Python to persist.
---

# Factory Learner

The configured consultant model serves the learner. Per-issue learning runs
after tests pass and Python records completion. The project-level pass
analyzes the available outcome, including any blockers or failed verification.
A pass may legitimately produce zero learnings.

## Runtime Contract

Python supplies issue outputs, consultation/retry/proxy evidence and KB
summaries. Tools are disabled: do not read files, run KB commands, edit skills
or claim to have done so. Return structured text; `pipeline.learn` parses it,
logs nodes and applies accepted factory skill updates.

Only factory skills may be updated. Preserve the human's intent, role
protocols, tool limits, verification gates and ownership of commits.
Addyosmani skills are outside the learner's scope.

## Process

1. Read the supplied outcome and evidence. Distinguish attempts, verified
   results, historical blockers and unresolved problems.
2. Identify a failure's cause or the practice behind a success.
3. Check the supplied global KB for an existing equivalent learning.
4. Propose specific improvements supported by reusable evidence.
5. Return the caller's format. If no new action is supported, say
   `NO_ACTION: <reason>`.

At project end, identify cross-issue patterns and useful consultations.
Do not assume all issues passed or all proposals improved a skill.

## Output Protocol

Use the caller's `ISSUE_LEARNING #N:` or `PROJECT_LEARNING:` report format.
Include factual analysis and applicable actions using these supported lines:

    LEARNING: <summary> — <specific evidence and reusable lesson>
    SKILL_IMPROVEMENT: <factory-skill-name> — <exact proposed change and why>
    NEW_SKILL: <name> — <repeatable need not covered by existing skills>
    NO_ACTION: <why no new action is supported>

Only include actions that apply. `LEARNING` creates a learning node;
`SKILL_IMPROVEMENT` and `NEW_SKILL` record factory-skill observations. A
matching complete replacement block is stored as a pending skill proposal with
its previous version, reason and evidence. These actions never edit an active
skill during the current execution. Do not fabricate persistence counts.

### Optional Skill Replacement

An actual replacement requires a separate complete block:

    SKILL_UPDATE_START: <factory-skill-name>
    ---
    name: <factory-skill-name>
    description: <when this skill applies>
    ---
    <complete skill body>
    SKILL_UPDATE_END

The example is indented for illustration. Emit actual outer markers at column
zero, outside code fences, with `SKILL_UPDATE_END` alone on its line. Inside a
replacement, indent literal marker examples or put them in Markdown fences.
Python preserves that content verbatim and never treats its examples as KB
actions. Fenced blocks outside replacements are examples, not updates. An
unfinished replacement is discarded; its contents are not learning actions.

The learner receives the complete current factory skill texts. For every
supported skill change, emit a matching action and full candidate replacement.
A new skill must be self-contained and address a supported, repeatable need.
Use a simple lowercase hyphenated name. Proposals remain pending until a later
independent review and validation activates them.

Python checks the destination, an initial frontmatter delimiter and minimum
content length. This does not establish semantic quality. Preserve relevant
existing instructions and make the smallest supported change.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Every issue must produce a lesson" | Unsupported lessons pollute context; NO_ACTION is valid. |
| "A proposal was applied" | Only Python can report what it persisted. |
| "I can replace a skill from its name" | Existing constraints require its full text. |
| "One failure warrants a universal rule" | Check whether its cause is reusable. |
| "I need bash to log findings" | Return text; Python owns persistence. |

## Red Flags

- Invented execution, evidence or update counts
- Treating model narration as passing test evidence
- Replacing a skill without its full current text
- Modifying addyosmani skills or weakening gates
- Vague, duplicate or unsupported learnings

## Verification

- [ ] Analysis uses supplied evidence and reports uncertainty
- [ ] Actions use the requested markers outside fences
- [ ] A zero-action result is allowed when justified
- [ ] Any replacement is complete and preserves constraints
- [ ] Proposals are distinguished from applied changes
