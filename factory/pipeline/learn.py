"""Factory learning: per-issue micro-learning (hook) and Phase 7 project summary.

Ports factory/hooks/learn-issue.sh and factory/scripts/learn.sh. The parse-
and-act side is unit-tested; the model calls are exercised via fake-pi.
"""
import re
import sys
from pathlib import Path

from pipeline import text
from pipeline.kb import Graph
from pipeline.pi import FACTORY_SKILLS, log, ok, run_pi

# "ISSUE_LEARNING #2:" / "PROJECT_LEARNING:" report blocks
ISSUE_LEARN = re.compile(r"^ISSUE_LEARNING.*$", re.M)
PROJECT_LEARN = re.compile(r"^PROJECT_LEARNING:.*$", re.M)

_KIND_NODE = {"LEARNING": "learning", "SKILL_IMPROVEMENT": "decision",
              "NEW_SKILL": "decision"}
_KIND_COUNT = {"LEARNING": "learnings", "SKILL_IMPROVEMENT": "improvements",
               "NEW_SKILL": "new_skills"}


def act_on_learnings(output: str, gkb: Graph, n: int | None) -> dict:
    """Log LEARNING/SKILL_IMPROVEMENT/NEW_SKILL lines to the global KB."""
    counts = {"learnings": 0, "improvements": 0, "new_skills": 0}
    for kind, summary, detail in text.learnings(output):
        if kind == "LEARNING":
            gkb.node("learning", summary, detail)
        else:
            gkb.node("decision", f"Skill improvement: {summary} (issue #{n})"
                     if kind == "SKILL_IMPROVEMENT"
                     else f"New skill proposed: {summary} (issue #{n})", detail)
        counts[_KIND_COUNT[kind]] += 1
    return counts


def apply_skill_updates(output: str, skills_dir: Path) -> list[str]:
    """SKILL_UPDATE_START/END blocks -> rewrite or create factory skills.

    Only factory skills are writable; addyosmani skills live elsewhere and
    are never touched by the learner.
    """
    applied = []
    for name, content in text.skill_updates(output):
        target = skills_dir / name.replace("/", "") / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n")
        applied.append(name)
    return applied


def _report(output: str, marker: re.Pattern, span: int) -> str:
    m = marker.search(output)
    return text.after(output, m, span) if m else ""


# ─── Per-issue learning ──────────────────────────────────────────────────

ISSUE_LEARN_PROMPT = """You are the factory-learner. Follow the factory-learner skill.
Analyze what happened during issue #{n} and learn from it. Be VERY granular and specific.

ISSUE #{n}:
{issue_text}

WHAT HAPPENED:
{happened}

ISSUE OUTPUT (first 100 lines):
{issue_output}

{evidence}
GLOBAL KB (learnings from ALL previous issues across ALL projects):
{global_kb}

CURRENT FACTORY SKILLS (can improve these):
{skills}

Analyze with these specific questions:
1. Did the worker get stuck? WHY specifically? What was missing in the skill that could have prevented this?
2. If consulted, what was the question? Could the issue-executor skill cover this topic so future issues don't need to consult?
3. If proxy rejected, what was wrong with the worker's approach? What Red Flag should be added to prevent this?
4. If retried, what was the first attempt's mistake?
5. What decision was made? Is it a pattern that could repeat?
6. What went WELL that should be preserved as a best practice?
7. Is there a new pattern that no skill covers? (Only if truly novel AND likely to repeat)

Be EXTREMELY specific. Instead of 'improve testing', say 'add test for empty input in function X'.
Instead of 'worker made mistake', say 'worker tried approach X but should have used Y because Z'.

Output EXACTLY in this format:

ISSUE_LEARNING #{n}:
  Stuck: {stuck}
  Consulted: {stuck}
  Proxy rejection: {proxy}
  Retried: {retry}
  Blocked: {blocked}

  What went wrong:
    - <specific issue, or 'nothing'>

  Root cause:
    - <why it happened, or 'n/a'>

  What the skill should cover:
    - <specific guidance that was missing, or 'nothing'>

  What to do differently next time:
    - <actionable change, or 'nothing'>

  What went well:
    - <specific thing that worked, or 'nothing'>

  Actions:
    SKILL_IMPROVEMENT: <skill-name> — <exactly what to add and where>
    SKILL_IMPROVEMENT: <skill-name> — <what to add> (if more than one)
    NEW_SKILL: <name> — <what it covers> (only if truly novel)
    LEARNING: <summary> — <detail to log to global KB>
    LEARNING: <summary> — <detail> (if more than one)
    NO_ACTION: nothing to learn (rare)

  If improving a skill, also output the updated content block:
  SKILL_UPDATE_START: <skill-name>
  <full updated SKILL.md content>
  SKILL_UPDATE_END"""


def _issue_facts(proj: Path, n: int, issue_text: str, kb: Graph) -> dict:
    def readable(name: str) -> str | None:
        p = proj / name
        return p.read_text() if p.exists() else None

    issue_output = readable(f"issue_{n}_output.txt")
    consult = readable(f"consult_{n}_output.txt")
    proxy = readable(f"proxy_{n}_output.txt")
    retry = readable(f"issue_{n}_retry_output.txt")
    blocked = any(f"Issue #{n}" in node["summary"]
                  for node in kb.query(type_="blocker"))
    return {
        "issue_text": text.head(issue_text, 30),
        "issue_output": issue_output or "",
        "consult": consult, "proxy": proxy, "retry": retry,
        "flags": {
            "consult": consult is not None,
            "proxy": proxy is not None,
            "retry": retry is not None,
            "blocker": blocked,
        },
    }


def learn_issue(proj: Path, n: int, issue_text: str, kb: Graph, gkb: Graph) -> str:
    """Micro-learning after one issue. Returns the transcript for the log."""
    facts = _issue_facts(proj, n, issue_text, kb)
    flags = facts["flags"]
    happened = []
    if flags["consult"]:
        happened.append("- Worker got STUCK and consulted the senior model")
    if flags["proxy"]:
        happened.append("- Worker requested PROXY approval")
    if flags["retry"]:
        happened.append("- Worker RETRIED (failed first attempt)")
    if flags["blocker"]:
        happened.append("- Issue was BLOCKED")
    if not any(flags.values()):
        happened.append("- Issue executed cleanly (no issues)")

    evidence = ""
    if flags["consult"]:
        evidence += f"CONSULTATION (worker asked the consultant):\n{text.head(facts['consult'], 50)}\n---\n"
    if flags["proxy"]:
        evidence += f"PROXY DECISION:\n{text.head(facts['proxy'], 30)}\n---\n"
    if flags["retry"]:
        evidence += f"RETRY OUTPUT (second attempt):\n{text.head(facts['retry'], 50)}\n---\n"

    body = ISSUE_LEARN_PROMPT.format(
        n=n, issue_text=facts["issue_text"], happened="\n".join(happened),
        issue_output=text.head(facts["issue_output"], 100), evidence=evidence,
        global_kb=gkb.compact(),
        skills=", ".join(p.name for p in FACTORY_SKILLS.iterdir() if p.is_dir()),
        stuck=str(flags["consult"]).lower(),
        proxy=str(flags["proxy"]).lower(),
        retry=str(flags["retry"]).lower(),
        blocked=str(flags["blocker"]).lower())
    out = run_pi("worker", body, f"Learn from issue #{n}", thinking="off",
                 skills=(FACTORY_SKILLS / "factory-learner", FACTORY_SKILLS / "kb-manager"),
                 cwd=proj, tools="no", artifact=proj / f"learning_issue_{n}.txt")

    counts = act_on_learnings(out, gkb, n)
    applied = apply_skill_updates(out, FACTORY_SKILLS)
    if applied:
        log(f"Applied skill updates: {', '.join(applied)}")
    transcript = "\n".join([
        f"Issue #{n} learning complete:",
        f"  Learnings logged:     {counts['learnings']}",
        f"  Skill improvements:   {counts['improvements']}",
        f"  New skills proposed:  {counts['new_skills']}",
        f"  Global KB nodes:      {len(gkb.query(summary_only=True))}",
        _report(out, ISSUE_LEARN, 30), ""],
    )
    return transcript.rstrip() + "\n"


# ─── Project-level learning (Phase 7) ────────────────────────────────────

PROJECT_LEARN_PROMPT = """You are the factory-learner. Follow the factory-learner skill (Level 2: Project-End Learning).

Per-issue learning already happened. Now do the PROJECT-LEVEL summary.

PROJECT: {name}

ALL PER-ISSUE LEARNINGS (from this project):
{issue_learnings}

PROJECT KB:
Blockers ({blockers}): {blocker_nodes}
Consultations ({consults}): {consult_nodes}
Decisions ({decisions}): {decision_nodes}

GLOBAL KB (all learnings including per-issue from this project):
{global_kb}

CURRENT FACTORY SKILLS:
{skills}

Your job (project-level):
1. Identify CROSS-ISSUE patterns — things that appeared in multiple issues
2. Check if any factory skill should be RESTRUCTURED (not just appended to)
3. Were there related blockers across issues? Same root cause?
4. Were consultations about the same topic? Skill should cover that topic
5. What's the overall project learning? (one paragraph)
6. Should a new skill be created based on cross-issue patterns?

Output EXACTLY:

PROJECT_LEARNING:
  Project: {name}
  Issues executed: N
  Blockers: {blockers}
  Consultations: {consults}
  Decisions: {decisions}

  Cross-issue patterns:
    - <pattern that appeared in multiple issues, or 'none'>

  Skills to restructure:
    - <skill-name>: <what structural change is needed, or 'none'>

  New skills (from cross-issue patterns):
    - <name>: <what it covers, or 'none'>

  Overall project learning:
    <one paragraph summary of what this project taught the factory>

  Actions:
    LEARNING: <summary> — <detail to log to global KB>
    LEARNING: <summary> — <detail> (if more)
    SKILL_IMPROVEMENT: <skill> — <structural change> (if any)
    NEW_SKILL: <name> — <what> (if any)

  If restructuring a skill, output the full updated content:
  SKILL_UPDATE_START: <skill-name>
  <full updated SKILL.md>
  SKILL_UPDATE_END"""


def learn_project(proj: Path, name: str, kb: Graph, gkb: Graph) -> str:
    """Phase 7: cross-issue analysis. Returns the transcript for the log."""
    chunks = []
    for f in sorted(proj.glob("learning_issue_*.txt")):
        out = f.read_text()
        report = _report(out, ISSUE_LEARN, 30)
        if report:
            chunks.append(report)
    issue_learnings = "\n---\n".join(chunks) or "No per-issue learning files found."

    body = PROJECT_LEARN_PROMPT.format(
        name=name, issue_learnings=issue_learnings,
        blockers=len(kb.query("blocker")), blocker_nodes=kb.compact("blocker"),
        consults=len(kb.query("consultation")), consult_nodes=kb.compact("consultation"),
        decisions=len(kb.query("decision")), decision_nodes=kb.compact("decision"),
        global_kb=gkb.compact(),
        skills=", ".join(p.name for p in FACTORY_SKILLS.iterdir() if p.is_dir()))
    out = run_pi("worker", body, name, thinking="off",
                 skills=(FACTORY_SKILLS / "factory-learner", FACTORY_SKILLS / "kb-manager"),
                 cwd=proj, tools="no", artifact=proj / "project_learning_output.txt")

    counts = act_on_learnings(out, gkb, None)
    applied = apply_skill_updates(out, FACTORY_SKILLS)
    if applied:
        log(f"Applied project-level skill updates: {', '.join(applied)}")
    transcript = "\n".join([
        "Project-level learning complete!",
        f"  New learnings logged: {counts['learnings']}",
        f"  Global KB: {len(gkb.query(summary_only=True))} nodes",
        _report(out, PROJECT_LEARN, 35), ""],
    )
    ok(f"Project-level learning complete: {counts['learnings']} new learnings")
    return transcript.rstrip() + "\n"