"""Entry point: python3 -m pipeline "<idea>" [--auto] [--resume].

Owns the checkpoint file, the failure-learning trap, phase dispatch and the
final summary. Phase bodies live in pipeline/phases.py, learning in
pipeline/learn.py.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from pipeline import learn, phases, text
from pipeline.kb import Graph
from pipeline.pi import (CONFIG, FACTORY, GLOBAL_KB, ROLE, _declared_context,
                         warn_if_context_mismatch, err, log, ok, phase, warn)

PHASE_ORDER = ["phase-0", "phase-1", "phase-2", "phase-3",
               "phase-4", "phase-5", "complete"]

# Run evidence stays on disk (learn.py reads these inputs) but is never
# product — every pattern here is also what `git clean -fd` (no -x)
# preserves, so the #49 residue discard never destroys evidence.
GITIGNORE = (
    ".DS_Store\n__pycache__/\n*.pyc\n.pytest_cache/\n"
    ".pi/\n.qwen/\n.claude/\n.pipeline-checkpoint\n"
    # .pipeline-idea is run bookkeeping the #56 guard reads on relaunch —
    # ignored (not product, never committed) but preserved by clean -fd.
    ".pipeline-idea\n"
    "verify_verdict.txt\n"
    "*_output.txt\ninterview_closeout.txt\nregression_*.log\n"
    "regression_repair_*.txt\n"
    "pre_issue_*.json\nlearning_issue_*.txt\nproject_learning.*\n")


def slug(idea: str) -> str:
    """Lowercase-hyphenated project name, cut at the last word under 40 chars."""
    name = re.sub(r"[^a-z0-9]+", "-", idea.lower()).strip("-")
    if len(name) > 40:
        name = re.sub(r"-[^-]*$", "", name[:40])
    return name or f"project-{int(time.time())}"


def _norm_idea(s: str) -> str:
    """Ignore case and whitespace when comparing recorded project ideas."""
    return re.sub(r"\s+", " ", s.lower()).strip()


IDEA_FILE = ".pipeline-idea"


def _latest(kb: Graph, type_: str) -> str | None:
    nodes = kb.query(type_=type_)
    return nodes[-1]["id"] if nodes else None


def _blocked_from_kb(kb: Graph) -> list[int]:
    """Rebuild blocked issues from the persisted ledger.
    Completion outranks an earlier blocker for the same issue."""
    completed = {n["summary"] for n in kb.query(type_="decision")}
    blocked: list[int] = []
    for node in kb.query(type_="blocker"):
        m = re.search(r"[Ii]ssue #(\d+)", node["summary"])
        if not m:
            continue  # run-level blockers (stop.md, pipeline failed) carry no number
        num = int(m.group(1))
        if f"Issue #{num} completed" not in completed and num not in blocked:
            blocked.append(num)
    return sorted(blocked)


def _warn_context_mismatches() -> None:
    """Warn once per model if its served window is smaller than declared.
    This is advisory: an unavailable probe must not halt the pipeline."""
    seen: set[str] = set()
    for role in ("planner", "worker", "consultant"):
        model = ROLE[role]["model"]
        if model in seen:
            continue          # planner and consultant share GLM — warn once
        seen.add(model)
        try:
            warn_if_context_mismatch(model, _declared_context(model))
        except Exception:
            pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="siesta")
    ap.add_argument("--auto", action="store_true",
                    help="skip the interview; use the idea as the intent")
    ap.add_argument("--resume", action="store_true",
                    help="skip phases already completed per checkpoint")
    ap.add_argument("idea", nargs="?")
    args = ap.parse_args(argv)
    if not args.idea:
        err('Usage: siesta "project idea" [--auto] [--resume]')
        sys.exit(1)
    try:
        _run(args)
    except (SystemExit, KeyboardInterrupt) as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            raise  # clean stop (e.g. stop.md) — nothing to learn
        _failure_learn(args, e)
        raise
    except Exception as e:  # like bash's EXIT trap: any crash still learns
        _failure_learn(args, e)
        raise


def _failure_learn(args, e) -> None:
    """Record failed execution in both project and global knowledge bases."""
    name = slug(args.idea)
    proj = FACTORY / "projects" / name
    checkpoint = proj / ".pipeline-checkpoint"
    last = checkpoint.read_text().strip() if checkpoint.exists() else "none"
    warn(f"Pipeline failed ({type(e).__name__}: {e}). Logging failure to KB...")
    Graph(proj / "kb" / "graph.json").node(
        "blocker", "Pipeline failed",
        f"Pipeline exited with error: {e}. Last checkpoint: {last}.")
    Graph(GLOBAL_KB, seed=GLOBAL_KB.with_name("global-seed.json")).node(
        "learning", f"Pipeline failure: {name}",
        f"Pipeline failed at checkpoint {last}. Error: {e}.")
    err("Pipeline failed. KB updated with failure details.")


def _run(args) -> None:
    log(f"Model configuration: {os.path.relpath(CONFIG)}")
    for role, route in ROLE.items():
        log(f"Model {role}: {route['model']} (provider: {route['provider']})")
    idea = args.idea
    name = slug(idea)
    proj = FACTORY / "projects" / name
    checkpoint = proj / ".pipeline-checkpoint"
    # #51: the same idea always slug-maps to the same dir, so a relaunch
    # is silently a resume — the operator must be able to tell them apart.
    if checkpoint.exists():
        log(f"Resuming project: {name} (checkpoint: "
            f"{checkpoint.read_text().strip() or 'unknown'})")
        # Truncated slugs can collide. Never resume a different recorded idea.
        idea_file = proj / IDEA_FILE
        if idea_file.exists() and \
                _norm_idea(idea_file.read_text()) != _norm_idea(idea):
            err(f"Project dir exists for a DIFFERENT idea: {proj}")
            err(f'  recorded idea: "{idea_file.read_text().strip()}"')
            err(f'  current  idea: "{idea}"')
            err("Resume is for continuing the same idea. Pick a different "
                "wording (the slug truncates at 40 chars) or remove the "
                "old project dir to start fresh.")
            raise SystemExit(1)
    else:
        log(f"Creating project: {name}")
        # record the idea — the #56 collision guard reads this on relaunch
        proj.mkdir(parents=True, exist_ok=True)
        (proj / IDEA_FILE).write_text(idea + "\n")
    _warn_context_mismatches()
    proj.mkdir(parents=True, exist_ok=True)
    # #7: generated projects commit with `git add -A` — give them the same
    # hygiene ignore list the factory itself uses, from the very first commit.
    # #38: run evidence (model outputs, regression logs, pre-issue contexts,
    # learning transcripts) stays on disk — learn.py reads these inputs —
    # but is never product: keep it out of the commits.
    gitignore = proj / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE)

    # Seed the KB only when missing — --resume must not wipe a project's memory.
    kb = Graph(proj / "kb" / "graph.json")
    if len(kb.query()) == 0 and not (proj / "kb" / "schema.json").exists():
        schema = FACTORY / "kb" / "schema.json"
        if schema.exists():
            (proj / "kb" / "schema.json").write_text(schema.read_text())
    gkb = Graph(GLOBAL_KB, seed=GLOBAL_KB.with_name("global-seed.json"))
    if not (proj / ".git").exists():
        phases._git(proj, "init")

    def done(ph: str) -> bool:
        # Monotonic: checkpoint "phase-2" skips 0 and 1 too — the bash
        # equality check re-interviewed the human on --resume.
        if not checkpoint.exists():
            return False
        value = checkpoint.read_text().strip()
        return value in PHASE_ORDER and PHASE_ORDER.index(value) >= PHASE_ORDER.index(ph)

    def mark(value: str) -> None:
        # Only ever move forward; a skipped phase must not rewind.
        if not done(value):
            checkpoint.write_text(f"{value}\n")

    # On --resume the intent comes from the recorded interview output.
    intent = text.intent_from(
        (proj / "interview_output.txt").read_text(errors="replace")
        if (proj / "interview_output.txt").exists() else "",
        idea)
    intent_node = None
    spec_node = None

    # ─── PHASE 0: HUMAN INTERACTIVE (or --auto) ──────────────────────────
    if done("phase-0"):
        log("Phase 0 already complete (resume mode), skipping...")
    else:
        phase(0, "INTENT — Define the idea")
        intent, intent_node = phases.phase0(proj, name, idea, args.auto, kb)
    mark("phase-0")

    # ─── PHASE 1: SPEC ───────────────────────────────────────────────────
    if done("phase-1"):
        log("Phase 1 already complete (resume mode), skipping...")
    else:
        phase(1, "SPEC — Generate the spec")
        # SPEC needs the intent node even when resumed past phase 0.
        intent_node = intent_node or _latest(kb, "intent") \
            or kb.node("intent", "Intent", intent)
        spec_node = phases.phase1(proj, name, intent, intent_node, kb)
    mark("phase-1")

    # ─── PHASE 2: PLAN ───────────────────────────────────────────────────
    if done("phase-2"):
        log("Phase 2 already complete (resume mode), skipping...")
    else:
        phase(2, "PLAN — Generate issues.md")
        spec_node = spec_node or _latest(kb, "spec")
        # #42: phase2's issue count is phase2's contract — log it, don't
        # discard the return value.
        count = phases.phase2(proj, name, spec_node, kb)
        log(f"Planned {count} issues")
    mark("phase-2")

    # Checkpoints record traversed phases; the issue ledger proves completion.
    issues = text.split_issues((proj / "issues.md").read_text())
    completed = {node["summary"] for node in kb.query(type_="decision")}
    pending = [num for num, _ in issues if f"Issue #{num} completed" not in completed]
    if pending and done("phase-3"):
        log(f"Pending issues {pending} — resuming execution and invalidating review/verify")
        checkpoint.write_text("phase-2\n")
        (proj / "verify_verdict.txt").unlink(missing_ok=True)
    elif done("phase-5"):
        saved_verdict = proj / "verify_verdict.txt"
        if not saved_verdict.exists() or saved_verdict.read_text().strip() != "VERIFY_PASSED":
            log("Previous verification was not successful — verifying again")
            checkpoint.write_text("phase-4\n")

    # ─── PHASE 3: EXECUTE (per-issue loop) ───────────────────────────────
    if done("phase-3"):
        log("Phase 3 already complete (resume mode), skipping...")
        blocked = _blocked_from_kb(kb)
    else:
        phase(3, "EXECUTE — Implement every issue")
        blocked = phases.execute(proj, kb)
    mark("phase-3")

    # ─── PHASE 4: REVIEW ─────────────────────────────────────────────────
    if done("phase-4"):
        log("Phase 4 already complete (resume mode), skipping...")
    else:
        phase(4, "REVIEW — Code review")
        phases.review(proj, kb)
    mark("phase-4")

    # ─── PHASE 5: VERIFY (+ runtime smoke check) ─────────────────────────
    if done("phase-5"):
        log("Phase 5 already complete (resume mode), skipping...")
        # #6: read the real recorded verdict — a resume must not invent a pass.
        verdict = ((proj / "verify_verdict.txt").read_text().strip()
                   if (proj / "verify_verdict.txt").exists() else "VERIFY_UNKNOWN")
    else:
        phase(5, "VERIFY — Runs locally?")
        verdict = phases.verify(proj)
    mark("phase-5")

    # ─── PHASE 6: DONE ───────────────────────────────────────────────────
    if done("complete"):
        # #57: a completed project's relaunch printed the summary but ALSO
        # re-ran phase 6 (duplicate "Project verified" commit) and phase 7
        # (duplicate project-level learnings in the global KB) — a done
        # project must stay done.
        log("Project already complete (resume mode) — nothing left to do")
        blocked = _blocked_from_kb(kb)
        _summary(proj, name, kb, blocked)
        return
    phase(6, "DONE")
    # #6: the decision node and the commit message tell the truth about the
    # verdict — never "verified" for a project that failed verify.
    if verdict == "VERIFY_PASSED" and not blocked:
        kb.node("decision", f"Project complete: {name}",
                "Project verified running locally.")
        phases._commit(proj, f"Project verified: {name}")
    else:
        kb.node("blocker", f"Project NOT verified: {name}",
                f"Verify verdict: {verdict}; blocked issues: {blocked}.")
        phases._commit(proj, f"Project delivered UNVERIFIED: {name}")

    # ─── PHASE 7: LEARN (project-level) ──────────────────────────────────
    phase(7, "LEARN — Project-level learning")
    transcript = learn.learn_project(proj, name, kb, gkb)
    (proj / "project_learning.log").write_text(transcript)
    if blocked or verdict != "VERIFY_PASSED":
        checkpoint.write_text("phase-2\n" if blocked else "phase-4\n")
        _summary(proj, name, kb, blocked)
        err("Project incomplete; resume will retry pending work")
        raise SystemExit(1)
    mark("complete")

    # ─── Summary ─────────────────────────────────────────────────────────
    ok("Siesta pipeline complete!")
    _summary(proj, name, kb, blocked)


def _summary(proj: Path, name: str, kb: Graph, blocked: list[int]) -> None:
    git_log = subprocess.run(["git", "-C", str(proj), "log", "--oneline"],
                             capture_output=True, text=True).stdout.splitlines()
    try:
        issue_count = len(text.split_issues((proj / "issues.md").read_text()))
    except OSError:
        issue_count = 0
    print(f"""
  Project:   {name}
  Location:  {proj}
  Issues:    {issue_count} total, {len(blocked)} blocked
  """)
    if git_log:
        print("  Git log:")
        print("\n".join(f"  {line}" for line in git_log[:20]))
    if blocked:
        warn(f"Blocked issues: {', '.join(f'#{n}' for n in blocked)}")
    print(f"\n  KB stats: {len(kb.query())} nodes, "
          f"{len(kb.data['edges'])} edges")


if __name__ == "__main__":
    main()
