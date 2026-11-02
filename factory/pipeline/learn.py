"""Per-issue and project learning, KB records and factory skill proposals."""
import json
import re
from pathlib import Path

from pipeline import text
from pipeline.kb import Graph
from pipeline.pi import FACTORY_SKILLS, log, ok, run_pi, warn
from pipeline import skill_versions

# "ISSUE_LEARNING #2:" / "PROJECT_LEARNING:" report blocks
ISSUE_LEARN = re.compile(r"^ISSUE_LEARNING.*$", re.M)
PROJECT_LEARN = re.compile(r"^PROJECT_LEARNING:.*$", re.M)

_KIND_COUNT = {"LEARNING": "learnings", "SKILL_IMPROVEMENT": "improvements",
               "NEW_SKILL": "new_skills"}


def act_on_learnings(output: str, gkb: Graph, n: int | None,
                     skills_dir: Path = FACTORY_SKILLS,
                     project: Path | None = None) -> dict:
    """Persist observations separately from complete, pending skill proposals."""
    counts = {"learnings": 0, "improvements": 0, "new_skills": 0}
    # round-5: n is None for project-level learning — that used to log
    # "(issue #None)" into the KB.
    where = f" (issue #{n})" if n is not None else " (project level)"
    roots = skill_versions.source_roots()
    roots["factory"] = Path(skills_dir)
    if project is not None:
        manifest = skill_versions.pin_project(project, roots=roots)
        factory_names = {item["name"] for item in manifest["skills"]
                         if item["scope"] == "factory"}
        adapted_names = {item["name"] for item in manifest["skills"]
                         if item["scope"] == "adapted"}
    else:
        factory_names = {path.name for path in Path(skills_dir).iterdir()
                         if path.is_dir() and not path.is_symlink()
                         and (path / "SKILL.md").is_file()} \
            if Path(skills_dir).is_dir() else set()
        adapted_root = roots["adapted"]
        adapted_names = {path.name for path in adapted_root.iterdir()
                         if path.is_dir() and not path.is_symlink()
                         and (path / "SKILL.md").is_file()} \
            if adapted_root.is_dir() else set()
    for kind, summary, detail in text.learnings(output):
        if kind == "LEARNING":
            gkb.node("learning", summary, detail)
        else:
            authorized = bool(_SKILL_NAME.fullmatch(summary))
            if kind == "SKILL_IMPROVEMENT":
                authorized = authorized and summary in factory_names
            else:
                authorized = authorized and summary not in adapted_names
            if not authorized:
                warn(f"Ignored {kind} outside the factory skill namespace: {summary!r}")
                continue
            gkb.node("skill_observation", f"{kind}: {summary}{where}",
                     json.dumps({"skill": summary, "reason": detail,
                                 "issue": n, "status": "observation"},
                                ensure_ascii=False))
        counts[_KIND_COUNT[kind]] += 1
    return counts


_SKILL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _complete_skill(name: str, content: str) -> bool:
    """Check a replacement has matching frontmatter and a complete body."""
    lines = content.strip().splitlines()
    if len(content.strip()) < 50 or len(lines) < 4 or lines[0] != "---":
        return False
    try:
        end = lines.index("---", 1)
    except ValueError:
        return False
    declared = re.search(r"^name:[ \t]*([a-z0-9-]+)[ \t]*$", "\n".join(lines[1:end]),
                         re.M)
    return bool(declared and declared.group(1) == name
                and any(line.strip() for line in lines[end + 1:]))


def propose_skill_updates(output: str, skills_dir: Path, gkb: Graph, *,
                          project: Path, issue: int | None,
                          evidence: dict | None = None) -> list[str]:
    """Store complete factory skill candidates without changing active files."""
    roots = skill_versions.source_roots()
    roots["factory"] = Path(skills_dir)
    manifest = skill_versions.pin_project(project, roots=roots)
    pinned = {(item["scope"], item["name"]) for item in manifest["skills"]}
    actions = {(kind, summary): detail for kind, summary, detail in text.learnings(output)
               if kind in ("SKILL_IMPROVEMENT", "NEW_SKILL")}
    records: list[str] = []
    seen: set[str] = set()
    source_root = Path(skills_dir)
    for name, content in text.skill_updates(output):
        if (not _SKILL_NAME.fullmatch(name) or name in seen
                or Path(name).name != name or ".." in name):
            warn(f"Rejected skill proposal with unauthorized name: {name!r}")
            continue
        seen.add(name)
        key = ("factory", name)
        new_skill = key not in pinned
        active = source_root / name / "SKILL.md"
        action_kind = "NEW_SKILL" if new_skill else "SKILL_IMPROVEMENT"
        reason = actions.get((action_kind, name), "").strip()
        if (new_skill and not actions.get(("NEW_SKILL", name), "").strip()
                or not new_skill and not reason):
            warn(f"Rejected skill proposal for {name}: no matching reason action")
            continue
        if (active.is_symlink() or (active.exists() and not active.is_file())
                or not _complete_skill(name, content)):
            warn(f"Rejected incomplete or unsafe skill proposal for {name}")
            continue
        adapted_root = roots["adapted"]
        if ((adapted_root / name / "SKILL.md").is_file()
                and key not in pinned):
            warn(f"Rejected proposal that targets adapted skill {name}")
            continue
        if not new_skill and key not in pinned:
            warn(f"Rejected skill proposal for unpinned factory skill {name}")
            continue
        previous = skill_versions.pinned_skill(project, name, roots=roots) or ""
        proof = {"learner_output": output,
                 "sources": evidence or {},
                 "project": Path(project).name,
                 "issue": issue}
        payload = {
            "version": 1,
            "skill": name,
            "scope": "factory",
            "previous_content": previous,
            "proposed_content": content.strip() + "\n",
            "reason": reason,
            "evidence": proof,
            "status": "pending",
        }
        proposal_id = gkb.node("skill_proposal", f"Skill proposal: {name}{where_for_issue(issue)}",
                              json.dumps(payload, ensure_ascii=False, sort_keys=True))
        records.append(proposal_id)
    return records


def where_for_issue(issue: int | None) -> str:
    return f" (issue #{issue})" if issue is not None else " (project level)"


def _review_proposals(ids: list[str], graph: Graph, project: Path) -> dict[str, str]:
    """Learning must never overturn a verified product verdict."""
    if not ids:
        return {}
    try:
        from pipeline.skill_activation import review_and_activate
        return review_and_activate(ids, graph, project=project)
    except Exception as exc:
        warn(f"Skill activation deferred: {exc}")
        return {proposal_id: "pending" for proposal_id in ids}


def _report(output: str, marker: re.Pattern, span: int) -> str:
    m = marker.search(output)
    return text.after(output, m, span) if m else ""


def _factory_skill_context(project: Path) -> str:
    manifest = skill_versions.pin_project(project)
    names = sorted(item["name"] for item in manifest["skills"]
                   if item["scope"] == "factory")
    sections = []
    for name in names:
        content = skill_versions.pinned_skill(project, name)
        if content:
            sections.append(f"### {name}\n{content.rstrip()}")
    return "\n\n".join(sections) or "No factory skills are available."


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

Use the supplied complete skill texts as the previous versions. A skill change
    is only a candidate: Python independently reviews and tests it before
    activation for future executions. This execution uses pinned versions.
    For every supported change, include a matching
SKILL_IMPROVEMENT or NEW_SKILL action and a complete replacement block. Do not
propose skills outside the factory skill list."""


def _issue_facts(proj: Path, n: int, issue_text: str, kb: Graph) -> dict:
    def readable(name: str) -> str | None:
        p = proj / name
        return p.read_text() if p.exists() else None

    issue_output = readable(f"issue_{n}_output.txt")
    consult = readable(f"consult_{n}_output.txt")
    proxy = readable(f"proxy_{n}_output.txt")
    retry = readable(f"issue_{n}_retry_output.txt")
    # Word-boundary match: "Issue #1" is also a substring of "Issue #10
    # blocked" — a completed issue #1 must not inherit a neighbor's
    # blocker, or the learner logs false facts into the global KB.
    blocked = any(re.search(rf"[Ii]ssue #{n}\b", node["summary"])
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
        skills=_factory_skill_context(proj),
        stuck=str(flags["consult"]).lower(),
        proxy=str(flags["proxy"]).lower(),
        retry=str(flags["retry"]).lower(),
        blocked=str(flags["blocker"]).lower())
    # #46: the learner emits the strictest output format in the pipeline
    # (LEARNING/SKILL_UPDATE blocks); gemma4 produced unparseable blocks in
    # two live runs — GLM holds the text protocol, so learning routes there.
    out = run_pi("consultant", body, f"Learn from issue #{n}", thinking="off",
                 skills=(FACTORY_SKILLS / "factory-learner", FACTORY_SKILLS / "kb-manager"),
                 cwd=proj, tools="no", artifact=proj / f"learning_issue_{n}.txt",
                 phase_name="learning")

    # Parse raw output: quoted actions are ignored, while examples inside a
    # replacement remain part of that file instead of becoming KB actions.
    counts = act_on_learnings(out, gkb, n, project=proj)
    proposal_ids = propose_skill_updates(
        out, FACTORY_SKILLS, gkb, project=proj, issue=n,
        evidence={key: value for key, value in facts.items()
                  if key in ("issue_text", "issue_output", "consult", "proxy", "retry")})
    outcomes = _review_proposals(proposal_ids, gkb, proj)
    if proposal_ids:
        log(f"Reviewed {len(proposal_ids)} skill proposal(s): {outcomes}")
    transcript = "\n".join([
        f"Issue #{n} learning complete:",
        f"  Learnings logged:     {counts['learnings']}",
        f"  Skill improvements:   {counts['improvements']}",
        f"  Complete proposals:  {len(proposal_ids)} ({outcomes})",
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

Use the supplied complete skill texts as the previous versions. A skill change
    is only a candidate: Python independently reviews and tests it before
    activation for future executions. This execution uses pinned versions.
    For every supported change, include a matching
SKILL_IMPROVEMENT or NEW_SKILL action and a complete replacement block. Do not
propose skills outside the factory skill list."""


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
        skills=_factory_skill_context(proj))
    # #46: same routing fix as learn_issue — GLM owns the strict format.
    out = run_pi("consultant", body, name, thinking="off",
                 skills=(FACTORY_SKILLS / "factory-learner", FACTORY_SKILLS / "kb-manager"),
                 cwd=proj, tools="no", artifact=proj / "project_learning_output.txt",
                 phase_name="learning")

    # Preserve replacement bodies while excluding their examples from actions.
    counts = act_on_learnings(out, gkb, None, project=proj)
    proposal_ids = propose_skill_updates(
        out, FACTORY_SKILLS, gkb, project=proj, issue=None,
        evidence={"project_learning": out, "issue_learnings": issue_learnings})
    outcomes = _review_proposals(proposal_ids, gkb, proj)
    transcript = "\n".join([
        "Project-level learning complete!",
        f"  New learnings logged: {counts['learnings']}",
        f"  Complete proposals: {len(proposal_ids)} ({outcomes})",
        f"  Global KB: {len(gkb.query(summary_only=True))} nodes",
        _report(out, PROJECT_LEARN, 35), ""],
    )
    ok(f"Project-level learning complete: {counts['learnings']} new learnings")
    return transcript.rstrip() + "\n"
