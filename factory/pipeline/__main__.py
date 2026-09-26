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

from pipeline import iterations, learn, phases, repository, text
from pipeline.kb import Graph
from pipeline.pi import (CONFIG, FACTORY, GLOBAL_KB, ROLE, _declared_context,
                         warn_if_context_mismatch, err, log, ok, phase, warn)

PHASE_ORDER = ["initialized", "phase-0", "phase-1", "phase-2", "phase-3",
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
    ap.add_argument("--project", type=Path, help="existing Siesta Git repository")
    ap.add_argument("--iterate", help="additional request for an existing project")
    ap.add_argument("--adopt-changes", action="store_true",
                    help="explicitly commit local product edits before continuing")
    ap.add_argument("idea", nargs="?")
    args = ap.parse_args(argv)
    if not args.idea and not args.project:
        ap.error('provide an idea or --project')
    if args.project and args.idea:
        ap.error('--project uses the saved intent; pass a new request with --iterate')
    if args.iterate is not None and (not args.project or not args.iterate.strip()):
        ap.error('--iterate requires --project and a nonempty request')
    # Selection and human-edit checks are read-only unless adoption is explicit.
    # Rejections here must not write failure nodes to someone else's project.
    try:
        args.proj, args.idea = _select_project(args)
        if (args.proj / '.git').exists() and (args.proj / 'stop.md').exists():
            warn('stop.md detected! Halting pipeline.')
            return
        if (args.proj / '.git').exists():
            checkpoint = args.proj / '.pipeline-checkpoint'
            if not checkpoint.exists() or checkpoint.read_text().strip() not in PHASE_ORDER:
                raise RuntimeError('Missing or invalid checkpoint in existing project; '
                                   'restore .pipeline-checkpoint from run evidence before resuming')
            repository.require_committed_ledger(args.proj)
            repository.completed_issues(args.proj)
            if args.adopt_changes:
                repository.adopt_changes(args.proj)
            repository.require_clean(args.proj)
    except (RuntimeError, OSError, ValueError) as exc:
        err(str(exc))
        raise SystemExit(1)
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


def _select_project(args) -> tuple[Path, str]:
    if args.project:
        proj = args.project.resolve()
        if not proj.is_dir():
            raise RuntimeError('--project must name an existing Siesta Git root')
        root = repository.checked_git(proj, 'rev-parse', '--show-toplevel').decode().strip()
        if Path(root).resolve() != proj or not all(
                (proj / name).is_file() for name in ('spec.md', 'issues.md', 'kb/graph.json')):
            raise RuntimeError('--project must name an existing Siesta Git root with spec, plan and KB')
        nodes = repository.committed_nodes(proj)
        intents = [node['detail'] for node in nodes if node['type'] == 'intent']
        if not intents:
            raise RuntimeError('--project has no committed Siesta intent')
        idea_file = proj / IDEA_FILE
        return proj, idea_file.read_text().strip() if idea_file.exists() else intents[0]
    proj = FACTORY / 'projects' / slug(args.idea)
    idea_file = proj / IDEA_FILE
    if idea_file.exists() and _norm_idea(idea_file.read_text()) != _norm_idea(args.idea):
        raise RuntimeError(f'Project dir exists for a DIFFERENT idea: {proj}. '
                           'Use --project with --iterate to extend it.')
    return proj, args.idea


def _failure_learn(args, e) -> None:
    """Record failed execution in both project and global knowledge bases."""
    proj = args.proj
    name = proj.name
    checkpoint = proj / ".pipeline-checkpoint"
    last = checkpoint.read_text().strip() if checkpoint.exists() else "none"
    state = repository.load_state(proj)
    try:
        changed = state.get('verified') and state['verified'] != repository.fingerprint(proj)
    except RuntimeError:
        changed = True
    if changed:
        state.clear()
        repository.save_state(proj, state)
        (proj / 'verify_verdict.txt').write_text('VERIFY_FAILED\n')
        checkpoint.write_text('phase-3\n')
    warn(f"Pipeline failed ({type(e).__name__}: {e}). Logging failure to KB...")
    try:
        repository.require_committed_ledger(proj)
    except RuntimeError as exc:
        warn(f'Failure record cannot safely commit: {exc}. Existing KB preserved.')
        return
    Graph(proj / "kb" / "graph.json").node(
        "blocker", "Pipeline failed",
        f"Pipeline exited with error: {e}. Last checkpoint: {last}.")
    Graph(GLOBAL_KB, seed=GLOBAL_KB.with_name("global-seed.json")).node(
        "learning", f"Pipeline failure: {name}",
        f"Pipeline failed at checkpoint {last}. Error: {e}.")
    # Commit only bookkeeping: failed worker edits must remain available for
    # explicit adoption, never silently become the next product base.
    try:
        repository.checked_git(proj, 'add', '--', 'kb')
        repository.checked_git(proj, 'commit', '--only', '-m', 'Record pipeline failure', '--', 'kb')
    except RuntimeError as exc:
        warn(f'Failure record remains uncommitted: {exc}')
    err("Pipeline failed. KB updated with failure details.")


def _run(args) -> None:
    log(f"Model configuration: {os.path.relpath(CONFIG)}")
    for role, route in ROLE.items():
        log(f"Model {role}: {route['model']} (provider: {route['provider']})")
    idea = args.idea
    proj = args.proj
    name = proj.name
    checkpoint = proj / ".pipeline-checkpoint"
    # #51: the same idea always slug-maps to the same dir, so a relaunch
    # is silently a resume — the operator must be able to tell them apart.
    if checkpoint.exists():
        log(f"Resuming project: {name} (checkpoint: "
            f"{checkpoint.read_text().strip() or 'unknown'})")
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
    if not checkpoint.exists():
        checkpoint.write_text('initialized\n')

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

    # Resume from the recorded intent, never from provider-log artifacts.
    intents = kb.query(type_='intent')
    intent = intents[0]['detail'] if intents else idea
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

    if args.iterate:
        iterations.prepare(proj, args.iterate, kb)

    # Checkpoints record traversed phases; the issue ledger proves completion.
    issues = repository.read_plan(proj)
    completed = repository.completed_issues(proj)
    pending = sorted(issues.keys() - completed)
    state = repository.load_state(proj)
    product = repository.fingerprint(proj)
    if pending and done("phase-3"):
        log(f"Pending issues {pending} — resuming execution and invalidating review/verify")
        checkpoint.write_text("phase-2\n")
        (proj / "verify_verdict.txt").unlink(missing_ok=True)
    elif done('phase-4') and state.get('reviewed') != product:
        log('Product changed or has no saved fingerprint — reviewing and verifying again')
        checkpoint.write_text('phase-3\n')
        (proj / 'verify_verdict.txt').unlink(missing_ok=True)
    elif done("phase-5"):
        saved_verdict = proj / "verify_verdict.txt"
        if (state.get('verified') != product or not saved_verdict.exists()
                or saved_verdict.read_text().strip() != "VERIFY_PASSED"):
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
        repository.require_clean(proj)
        state['reviewed'] = repository.fingerprint(proj)
        repository.save_state(proj, state)
    mark("phase-4")

    # ─── PHASE 5: VERIFY (+ runtime smoke check) ─────────────────────────
    if done("phase-5"):
        log("Phase 5 already complete (resume mode), skipping...")
        # #6: read the real recorded verdict — a resume must not invent a pass.
        verdict = ((proj / "verify_verdict.txt").read_text().strip()
                   if (proj / "verify_verdict.txt").exists() else "VERIFY_UNKNOWN")
    else:
        phase(5, "VERIFY — Runs locally?")
        before = repository.fingerprint(proj)
        verdict = phases.verify(proj)
        try:
            repository.require_clean(proj)
            if before != repository.fingerprint(proj):
                raise RuntimeError('Product content changed')
        except RuntimeError as exc:
            (proj / 'verify_verdict.txt').write_text('VERIFY_FAILED\n')
            state['verified'] = None
            repository.save_state(proj, state)
            kb.node('blocker', f'Project NOT verified: {name}',
                    'Product changed during verification; edits preserved for inspection')
            raise RuntimeError('Product changed during verification; inspect and commit '
                               'the preserved edits before resuming') from exc
        state['verified'] = before if verdict == 'VERIFY_PASSED' else None
        repository.save_state(proj, state)
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
    with repository.completion_record(proj, kb):
        if verdict == "VERIFY_PASSED" and not blocked:
            kb.node("decision", f"Project complete: {name}",
                    "Project verified running locally. Product SHA256: " + state['verified'])
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
