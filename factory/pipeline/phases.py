"""Pipeline phases 0-7: intent, spec, plan, execute, review, verify, done.

Every model call keeps the bash version's prompts and skills verbatim so a
run behaves identically, minus four latent bash bugs fixed along the way:
anchored markers, first-dash learning split, monotonic resume, single
issue count. See also pipeline/text.py for the parser side.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from pipeline import learn, text
from pipeline.kb import Graph
from pipeline.pi import (CONFIG, FACTORY_SKILLS, GLOBAL_KB, SKILLS, err, log,
                         ok, run_pi, warn)

WORKER_THINKING = "off"
CONSULTANT_THINKING = "off"

# pi -p can't read files, so source content is piped into the prompts.
SOURCE_EXTS = {"html", "css", "js", "ts", "py", "go", "rs", "json", "md",
               "sh", "jsx", "tsx", "vue", "svelte"}


# ─── Context gathering ───────────────────────────────────────────────────

def _project_files(proj: Path):
    # os.walk (topdown, with pruned dirs) instead of rglob: git's auto-gc
    # can delete .git/objects/* while a walk is inside them — rglob then
    # raises FileNotFoundError mid-iteration (live flake in test runs).
    pruned = {".git", "kb", ".pytest_cache", "__pycache__"}
    for root, dirs, files in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in pruned]
        for name in sorted(files):
            f = Path(root) / name
            if f.name in (".DS_Store", ".pipeline-checkpoint"):
                continue
            yield f


# #39: total prompt budget for gather() — per-file caps alone let the
# worker prompt grow unbounded on big projects and flood the model's
# context. ~120k chars ≈ 30k tokens: bounded, still room for real work.
GATHER_BUDGET = 120_000


def gather(proj: Path) -> str:
    files = [f for f in _project_files(proj)
             if f.suffix.lstrip(".") in SOURCE_EXTS]
    parts = []
    remaining = GATHER_BUDGET
    for i, f in enumerate(files):
        if remaining <= 0:
            parts.append(f"\n\n--- TRUNCATED: {len(files) - i} further "
                         f"source files not shown (context budget) ---")
            break
        content = text.head(f.read_text(errors="replace"), 500)
        header = f"\n\n--- File: {f.relative_to(proj)} ---\n"
        if len(header) + len(content) > remaining:
            cut = "\n--- (file cut mid-way: context budget) ---"
            room = remaining - len(header) - len(cut)
            shown = len(files) - i
            if room > 0:  # partial fit: keep the head that fits, say it was cut
                parts.append(header + content[:room] + cut)
                shown = len(files) - i - 1
            parts.append(f"\n\n--- TRUNCATED: {shown} further source "
                         f"files not shown (context budget) ---")
            break
        parts.append(header + content)
        remaining -= len(header) + len(content)
    return "".join(parts)


def _git(proj: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=proj, capture_output=True)


def _commit(proj: Path, msg: str) -> None:
    # round-5: a failed commit used to pass silently — the run "completed"
    # with an empty repo and no trace of why.
    _git(proj, "add", "-A")
    proc = _git(proj, "commit", "-m", msg)
    if proc.returncode != 0:
        warn(f"git commit failed in {proj}: "
             f"{proc.stderr.decode(errors='replace').strip()}")


# ─── Per-issue hooks (KB context before, decision + commit after) ────────

def pre_issue(proj: Path, n: int, kb: Graph, gkb: Graph) -> dict:
    ctx = {
        "issue": str(n),
        "kb_summaries": kb.query(summary_only=True),
        "decisions": kb.query(type_="decision", summary_only=True),
        "learnings": kb.query(type_="learning", summary_only=True),
        "blockers": kb.query(type_="blocker", summary_only=True),
        "principles": gkb.query(type_="principle", summary_only=True),
    }
    (proj / f"pre_issue_{n}.json").write_text(json.dumps(ctx))
    return ctx


def post_issue(proj: Path, n: int, output: str, kb: Graph) -> str:
    # round-5: takes the FINAL worker output, not issue_{n}_output.txt — a
    # success that arrived via retry/diagnosis used to log the degenerate
    # first attempt as the completion record.
    node_id = kb.node("decision", f"Issue #{n} completed", text.head(output, 200))
    _commit(proj, f"🔧 Issue #{n}: implemented")
    return node_id


# ─── Phase 0: INTENT ─────────────────────────────────────────────────────

INTERVIEW_PROMPT = """You are an interviewer. Follow the interview-me skill.
A human wants to build: {idea}

Ask ONE question at a time to clarify what they want. Wait for their answer.
Keep asking until ~95% confidence about:
- What exactly to build
- What tech stack to use
- What success looks like
- What is out of scope

When you have enough clarity, output:
INTENT_FINALIZED: <one paragraph summarizing what the human wants>"""


CLOSEOUT_PROMPT = """You are an interviewer closing an unfinished session. Follow the interview-me skill.
A human wanted to build: {idea}

You asked questions, the human left without answering. No one will answer
more questions. Decide autonomously with sensible defaults.

Original idea:
{idea}

Interview so far:
{transcript}

Output ONLY:
INTENT_FINALIZED: <one paragraph stating what to build, with your chosen
defaults made explicit>"""


def phase0(proj: Path, name: str, idea: str, auto: bool,
           kb: Graph) -> tuple[str, str]:
    """Interview (or auto-fill) the idea. Returns (intent, kb node id)."""
    out = proj / "interview_output.txt"
    if auto:
        log("Auto mode: using idea description as intent (no interview)")
        out.write_text(f"INTENT_FINALIZED: {idea}")
    else:
        print("━━━ Interactive Session — Human + Agent ━━━")
        print("The agent will ask questions to clarify your idea.\n")
        run_pi("planner", INTERVIEW_PROMPT.format(idea=idea), idea,
               skills=(SKILLS / "interview-me",), interactive=True, artifact=out,
               cwd=proj, tools="no")
        print("\n")
        ok("Interactive phase complete. Human is leaving.")
    interview_out = out.read_text()
    if not text.INTENT.search(interview_out):
        # #45: the human leaving mid-interview must not collapse the intent
        # to the raw one-liner — the planner closes it out autonomously once.
        warn("Interview ended without INTENT_FINALIZED — closing it out autonomously...")
        closeout = run_pi("planner",
                          CLOSEOUT_PROMPT.format(idea=idea, transcript=text.head(interview_out, 100)),
                          "Close out the interview now", skills=(SKILLS / "interview-me",),
                          cwd=proj, tools="no", artifact=proj / "interview_closeout.txt")
        if text.INTENT.search(closeout):
            interview_out = closeout
            out.write_text(interview_out)
            ok("Interview closed out autonomously — intent finalized with defaults")
        else:
            # #12: the raw idea is a fallback, not a success — say it loudly.
            warn("Close-out gave no INTENT_FINALIZED — falling back to the raw idea")
    intent = text.intent_from(interview_out, idea)
    intent_node = kb.node("intent", f"Human intent for {name}", intent)
    _commit(proj, "Intent captured")
    return intent, intent_node


# ─── Phase 1: SPEC ───────────────────────────────────────────────────────

SPEC_PROMPT = """You are a software architect. Follow the spec-driven-development skill.
The human has left. This is autonomous. No human will answer questions.

HUMAN INTENT:
{intent}

KB context:
{kb}

Standing architectural principles (mandatory for every project):
{principles}

Model config (use these exact model names in any documentation):
{models}

You have NO TOOLS — you cannot read or write files. What the pipeline does with
your answer is stated in the final message below.

spec.md contains: project name, tech stack, structure, features, acceptance
criteria, testing approach, boundaries. Be concise. Do NOT ask questions —
decide autonomously. Do NOT write code and do NOT build the product: this is
a SPECIFICATION DOCUMENT only. The spec describes the SPECIFIC product in the
HUMAN INTENT above: use its key concepts by name. Never output a generic
template with TBD/placeholder fields."""

# The final human message is the actual request (runs #3/#4: the model obeys
# the last turn, so the order lives here and the data lives in the body).
SPEC_DIRECTIVE = ("This is not a coding request — it is a documentation task. "
                  "You have NO TOOLS. Output ONLY the complete content of "
                  "spec.md as your final message. Do NOT write code.")

SPEC_RETRY_DIRECTIVE = (
    "Your previous answer was rejected: it was not a usable spec for THIS "
    "product. Write the specification for the product described in the system "
    "prompt: name its key concepts directly, no generic template, no TBD "
    "placeholders, no code. Output ONLY the complete content of spec.md.")


def _code_artifacts(proj: Path) -> int:
    return sum(1 for f in glob_code(proj))


# Code artifacts (stricter than SOURCE_EXTS: what counts as "the product")
CODE_EXTS = ("html", "py", "js", "ts", "go", "rs")


def glob_code(proj: Path):
    for f in _project_files(proj):
        if f.suffix.lstrip(".") in CODE_EXTS:
            yield f


def _retro_spec(proj: Path) -> None:
    lines = ["# Spec", ""]
    for f in glob_code(proj):
        lines.append(f"## File: {f.name}")
        lines.append(text.head(f.read_text(errors="replace"), 5))
        lines.append("...")
    lines += ["", "## Note",
              "Spec generated retroactively from artifacts produced during Phase 0."]
    (proj / "spec.md").write_text("\n".join(lines))


def phase1(proj: Path, name: str, intent: str, intent_node: str, kb: Graph) -> str:
    body = SPEC_PROMPT.format(intent=intent, kb=kb.compact(),
                              principles=Graph(GLOBAL_KB).compact("principle"),
                              models=CONFIG.read_text())
    out = run_pi("planner", body, SPEC_DIRECTIVE,
                 skills=(SKILLS / "spec-driven-development", FACTORY_SKILLS / "kb-manager"),
                 artifact=proj / "spec_output.txt", cwd=proj, tools="no")
    doc = text.spec_doc(out)
    if doc is not None and not text.shares_content(intent, doc):
        # round-3 + #40: a format-valid spec that names (almost) none of the
        # intent's concepts is a generic template hallucination, not a spec.
        warn("Spec shares too little content with the intent — generic template? Rejecting...")
        doc = None
    if doc is None:
        warn("No usable spec in model output. Retrying once with feedback...")
        out = run_pi("planner", body, SPEC_RETRY_DIRECTIVE,
                     skills=(SKILLS / "spec-driven-development",
                             FACTORY_SKILLS / "kb-manager"),
                     artifact=proj / "spec_retry_output.txt", cwd=proj, tools="no")
        doc = text.spec_doc(out)
        if doc is not None and not text.shares_content(intent, doc):
            warn("Spec still off-intent after retry — rejecting")
            doc = None
    if doc is not None:
        (proj / "spec.md").write_text(doc + "\n")
    else:
        warn("No usable spec in model output. Checking for existing artifacts...")
        if _code_artifacts(proj) > 0:
            log("Generating a retroactive spec from existing artifacts...")
            _retro_spec(proj)
        else:
            err("Spec generation failed and no existing artifacts found")
            raise SystemExit(1)
    ok("Spec generated")
    spec_node = kb.node("spec", f"Spec for {name}", (proj / "spec.md").read_text())
    kb.edge(spec_node, intent_node, "parent_of")
    _commit(proj, "Spec generated")
    return spec_node


# ─── Phase 2: PLAN ───────────────────────────────────────────────────────

PLAN_PROMPT = """You are a project planner. Follow the planning-and-task-breakdown skill.
The human has left. This is autonomous. No questions.

THE SPEC:
{spec}

You have NO TOOLS — you cannot read or write files. What the pipeline does with
your answer is stated in the final message below.

Each issue: a '## Issue #N: Title' header, then description, acceptance
criteria, dependencies. Every issue header must match exactly '## Issue #N: '
(N counting from 1) — no priority groupings, no other numbering styles.
Keep issues small and atomic. Do NOT write code — output the plan document only.

The plan runs under TDD with a regression gate: every issue must leave the
test suite non-empty and green. A scaffold/setup issue must include at least
one smoke test (e.g. a trivial passing test) — NEVER an empty test file or
"collects zero tests" as acceptance criteria."""

PLAN_DIRECTIVE = ("This is not a code review request — it is a planning task. "
                  "You have NO TOOLS. Output ONLY the complete content of "
                  "issues.md as your final message. Do NOT write code.")

PLAN_RETRY_DIRECTIVE = (
    "Your previous answer was rejected: it had no '## Issue #N: Title' "
    "headers. Output the plan document where EVERY issue begins with exactly "
    "'## Issue #N: Title' (N counting from 1). No priority sections, no '### 1.' "
    "numbering, no code.")

FALLBACK_ISSUE = """## Issue #1: Review, verify and complete the project

Review all code files in the project against the spec:
- Correctness: does each module do what the spec says?
- Completeness: any missing features or entry points?
- Quality: obvious bugs, dead code, missing error handling
Fix any issues found, ensure the test suite passes, and verify the project
runs locally.

**Acceptance criteria:**
- Implementation matches the spec's features and acceptance criteria
- Test suite (if present) passes
- The project's entry point runs without errors"""


def phase2(proj: Path, name: str, spec_node: str, kb: Graph) -> int:
    body = PLAN_PROMPT.format(spec=(proj / "spec.md").read_text())
    out = run_pi("planner", body, PLAN_DIRECTIVE,
                 skills=(SKILLS / "planning-and-task-breakdown",),
                 artifact=proj / "plan_output.txt", cwd=proj, tools="no")
    doc = text.issues_doc(out)
    if doc is None:
        # round-3: the model drifted to '### 1.' / priority sections — one
        # retry with the exact required format, then the honest fallbacks.
        warn("Plan output has no '## Issue #N:' headers. Retrying once with feedback...")
        out = run_pi("planner", body, PLAN_RETRY_DIRECTIVE,
                     skills=(SKILLS / "planning-and-task-breakdown",),
                     artifact=proj / "plan_retry_output.txt", cwd=proj, tools="no")
        doc = text.issues_doc(out)
    if doc is not None:
        (proj / "issues.md").write_text(doc + "\n")
    else:
        warn("No issues in model output. Checking for existing artifacts...")
        if _code_artifacts(proj) > 0:
            log("Creating single review-and-verify issue for existing artifacts...")
            (proj / "issues.md").write_text(FALLBACK_ISSUE + "\n")
        else:
            err("Plan generation failed and no existing artifacts found")
            raise SystemExit(1)
    ok("Plan generated")
    issues = text.split_issues((proj / "issues.md").read_text())
    for num, body in issues:
        header = text.head(body, 1)
        issue_node = kb.node("issue", f"Issue #{num}", header)
        kb.edge(issue_node, spec_node, "parent_of")
    _commit(proj, "Plan generated with issues")
    return len(issues)


# ─── Regression suite ────────────────────────────────────────────────────

RUNNERS = [("package.json", ["npm", "test"]),
           ("requirements.txt", [sys.executable, "-m", "pytest", "tests/"]),
           ("setup.py", [sys.executable, "-m", "pytest", "tests/"]),
           ("pyproject.toml", [sys.executable, "-m", "pytest", "tests/"]),
           ("go.mod", ["go", "test", "./..."])]


def _pytest_available() -> bool:
    try:
        import pytest  # noqa: F401
        return True
    except ImportError:
        return False


def _suite_dirs(proj: Path) -> list[str]:
    """Where test files actually live — #50: the pomodoro layout puts
    test_pomodoro_app.py at the root (no tests/ dir, no manifest); the
    gate used to answer 'no suite' while 8 real tests sat there."""
    dirs = []
    if any(proj.glob("test_*.py")) or any(proj.glob("*_test.py")):
        dirs.append(".")
    if (proj / "tests").is_dir():
        dirs.append("tests")
    return dirs


def _regression_command(proj: Path, suite_dir: str):
    """(command, is_pytest) for the first matching runner, else None."""
    for manifest, cmd in RUNNERS:
        if (proj / manifest).exists():
            if cmd[1:2] == ["test"] and "npm" in cmd:
                return cmd, False
            if "pytest" in cmd:
                # #50: run the suite where it actually lives, not a
                # hardcoded tests/ that the layout may not have.
                return [cmd[0], cmd[1], cmd[2], suite_dir], True
            return cmd, True
    return None


# pytest exits 5 when the suite exists but collects zero tests (exit 4 is
# usage error) — a scaffold issue legitimately ships empty test stubs, and
# the pomodoro run (#44) had every later issue skipped for that alone.
PYTEST_NO_TESTS = 5


def run_regression(proj: Path, n: int) -> str:
    """'passed' | 'failed' | 'skipped'. Skipped (no tests, no runner) is a
    distinct state — #13: absence of tests must not read as 'green'."""
    dirs = _suite_dirs(proj)
    if not dirs:
        return "skipped"
    # #50: every dir that holds test files counts — a root-level suite with
    # no manifest used to make the gate say 'no suite' (pomodoro layout).
    verdict = "skipped"
    for suite_dir in dirs:
        runner = _regression_command(proj, suite_dir)
        if runner is None:
            if suite_dir == "." and _pytest_available():
                runner = ([sys.executable, "-m", "pytest", "."], True)
            else:
                continue
        cmd, is_pytest = runner
        log(f"Running regression suite ({suite_dir})...")
        proc = subprocess.run(cmd, cwd=proj, capture_output=True, text=True)
        (proj / f"regression_{n}.log").write_text(proc.stdout + proc.stderr)
        if proc.returncode == PYTEST_NO_TESTS and is_pytest:
            # #44: "no tests collected" is absence, not breakage — a stub
            # test file must not arm the regression gate.
            log(f"Regression suite in {suite_dir} collected zero tests — "
                "nothing to guard")
            continue
        if proc.returncode != 0:
            err(f"Regression suite FAILED before issue #{n} ({suite_dir}).")
            return "failed"
        verdict = "passed"
    return verdict


# ─── Phase 3: EXECUTE ────────────────────────────────────────────────────

EXECUTE_PROMPT = """You are a developer. Follow the issue-executor skill.
Execute this issue:

{issue}

KB Context:
{kb}

Architectural principles (mandatory, see simplicity rule — fewer lines wins):
{principles}

Existing source files in the project:
{source}

Reference: definition-of-done.md for exit criteria.

Rules:
- Write code and tests for this issue
- Run tests and verify they pass
- If STUCK, output EXACTLY:
  CONSULT: <question>
  CONTEXT: <what you tried>
  CODE: <error or relevant code>
- If a skill says 'ask the human', output:
  PROXY_REQUEST: <what needs approval>
  CONTEXT: <why>
- Otherwise implement fully"""

PROXY_PROMPT = """You are the human-proxy. Follow the human-proxy skill.
A worker requests approval as if you were the human.

Request:
{request}

KB Context (original intent and all decisions):
{kb}

Evaluate against the original human intent in the KB.
Decide: APPROVED, REJECTED, or NEEDS_REVISION — and output the decision as a
line starting with the marker (e.g. APPROVED: <reason>). A decision line that
does not start with a marker counts as NOT approved."""

CONSULT_PROMPT = """You are a senior engineer. Follow the consultant-protocol skill.
A developer is stuck:

{consult}

KB Context:
{kb}

Provide a clear resolution with RESOLUTION: and APPROACH: and CODE:."""

DIAGNOSE_PROMPT = """You are a senior engineer doing a DEEP DIAGNOSIS.
An issue has failed multiple times. This is not a normal consultation — this is a diagnosis.

Issue:
{issue}

Failure history (what was tried and failed):
{history}

KB Context:
{kb}

Diagnose:
1. Is the approach fundamentally wrong? If so, what's the right approach?
2. Is the issue too complex to solve in one pass? Should it be broken down?
3. Is there a missing prerequisite that should be done first?
4. Is there an environment/tooling issue?
5. Should this issue be SKIPPED and the pipeline continue without it?

Output:
DIAGNOSIS: <root cause>
RECOMMENDATION: <fix or skip>
DETAILED_PLAN: <step-by-step fix, or 'SKIP: log blocker and continue'>
CODE: <if code fix needed>"""


# #42: named per-phase skill sets — the tuples were duplicated inline and
# the overlap (incremental-implementation + test-driven-development) was
# invisible. Named constants keep them greppable; RETRY_SKILLS is the
# shared pair the worker gets on every fed-back retry.
RETRY_SKILLS = (SKILLS / "incremental-implementation",
                SKILLS / "test-driven-development")
EXECUTE_SKILLS = (SKILLS / "incremental-implementation",
                  SKILLS / "test-driven-development",
                  SKILLS / "debugging-and-error-recovery",
                  FACTORY_SKILLS / "issue-executor",
                  FACTORY_SKILLS / "kb-manager")
REVIEW_SKILLS = (SKILLS / "code-review-and-quality",
                 SKILLS / "code-simplification")
REPAIR_SKILLS = (SKILLS / "debugging-and-error-recovery",
                 SKILLS / "test-driven-development")
VERIFY_SKILLS = (SKILLS / "test-driven-development",
                 SKILLS / "debugging-and-error-recovery")


def _worker(proj: Path, skills, body, issue_text, artifact: Path | None = None):
    return run_pi("worker", body, issue_text, skills=skills,
                  thinking=WORKER_THINKING, cwd=proj, artifact=artifact)


def _discard_residue(proj: Path, num: int, why: str) -> None:
    """#49: a blocked issue leaves its uncommitted work behind — and the
    residue can contradict the committed base (the pomodoro issue-#3
    residue deleted format_time while the committed test still imported
    it). Honest state: the issue did NOT complete, so tracked files go
    back to the last commit and untracked product files are removed.
    Ignored run evidence survives (clean without -x honors .gitignore);
    the KB survives too — it is the run's bookkeeping, not product.
    """
    status = _git(proj, "status", "--porcelain")
    if status.returncode:
        raise RuntimeError(f"Cannot inspect residue: {status.stderr.decode()}")
    if not status.stdout.strip():
        return
    # Preserve staged and new files before cleaning; ignored evidence stays put.
    git_dir = _git(proj, "rev-parse", "--absolute-git-dir")
    if git_dir.returncode:
        raise RuntimeError("Cannot locate Git directory for recovery backup")
    backup = Path(git_dir.stdout.decode().strip()) / "siesta-recovery" / f"{time.time_ns()}-issue-{num}"
    backup.mkdir(parents=True)
    for name, args in (("staged.patch", ("--cached",)), ("unstaged.patch", ())):
        diff = _git(proj, "diff", "--binary", *args)
        if diff.returncode:
            raise RuntimeError("Cannot back up product changes")
        (backup / name).write_bytes(diff.stdout)
    files = _git(proj, "ls-files", "-z", "--others", "--exclude-standard")
    if files.returncode:
        raise RuntimeError("Cannot list files for recovery backup")
    with tarfile.open(backup / "files.tar.gz", "w:gz") as archive:
        for name in set(os.fsdecode(files.stdout).split("\0")) - {""}:
            path = proj / name
            if path.exists() or path.is_symlink():
                archive.add(path, arcname=name, recursive=False)
    kb_dir = proj / "kb"
    saved = {p.relative_to(kb_dir): p.read_bytes()
             for p in kb_dir.rglob("*") if p.is_file()} \
        if kb_dir.is_dir() else {}
    restored = _git(proj, "restore", "--source=HEAD", "--staged", "--worktree", "--", ".")
    if restored.returncode:
        raise RuntimeError(f"Cannot restore product base; recovery: {backup}")
    # No -x: clean honors .gitignore, so ignored run evidence survives and
    # only the product residue dies (the -e list lived one pattern behind
    # the .gitignore once already — regression_repair_*.txt, #38/#49).
    cleaned = _git(proj, "clean", "-fd")
    for rel, data in saved.items():
        target = kb_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if cleaned.returncode:
        raise RuntimeError(f"Cannot clean product residue; recovery: {backup}")
    warn(f"Issue #{num} blocked with tree changes ({why}) — discarded "
         f"uncommitted residue; recovery copy: {backup}")


def _tree_is_clean(proj: Path) -> bool:
    status = _git(proj, "status", "--porcelain")
    if status.returncode:
        raise RuntimeError(f"Cannot inspect product tree: {status.stderr.decode()}")
    return not status.stdout.strip()


REPAIR_PROMPT = """You are a developer. The regression suite is RED.

Issue #{n} was about to execute, but the previous issues left failing tests:

Issue #{n} (NOT started yet, for context):
{issue}

Failing suite output:
{suite}

Existing source files in the project:
{source}

Fix the failing tests so the suite is green again. Run the tests and verify
they pass. Do NOT implement issue #{n} — only repair the regression."""


def _repair_regression(proj: Path, n: int, issue_text: str, source: str) -> bool:
    """One worker-driven repair of a red suite. Returns True if green after."""
    suite_log = proj / f"regression_{n}.log"
    suite_out = suite_log.read_text(errors="replace") if suite_log.exists() else ""
    log(f"Regression is red before issue #{n} — one repair attempt...")
    fix = run_pi("worker",
                 REPAIR_PROMPT.format(n=n, issue=text.head(issue_text, 40),
                                      suite=text.head(suite_out, 80),
                                      source=source),
                 f"Repair the failing regression suite before issue #{n}",
                 skills=REPAIR_SKILLS,
                 thinking=WORKER_THINKING, cwd=proj,
                 artifact=proj / f"regression_repair_{n}.txt")
    if text.degenerate(fix):
        warn("Regression repair output degenerate — attempting re-run anyway")
    return run_regression(proj, n) == "passed"


def execute(proj: Path, kb: Graph) -> list[int]:
    """Run every issue; return the numbers that stayed blocked."""
    issues = dict(text.split_issues((proj / "issues.md").read_text()))
    log(f"Found {len(issues)} issues to execute")
    gkb = Graph(GLOBAL_KB)
    blocked, fails, history = [], {}, {}
    warned_no_tests = False
    red_streak = 0  # consecutive red suites that stayed red after repair
    # #9: per-issue idempotency — a resume skips issues whose completion node
    # is already on disk (post_issue writes "Issue #N completed" decisions).
    # Blocked issues have no node, so they naturally get retried.
    completed = {n["summary"] for n in kb.query(type_="decision")}
    for num in sorted(issues):
        if f"Issue #{num} completed" in completed:
            log(f"Issue #{num} already completed (resume) — skipping")
            continue
        if (proj / "stop.md").exists():
            warn("stop.md detected! Halting pipeline.")
            kb.node("blocker", "Pipeline halted by stop.md",
                    (proj / "stop.md").read_text())
            raise SystemExit(0)
        log(f"Executing issue #{num}...")
        issue_text = issues[num]

        # #49 (b): never build on a tree that contradicts the committed base —
        # residue from a blocked issue of a previous run gets restored, not
        # silently inherited (untracked run evidence is not a contradiction).
        if not _tree_is_clean(proj):
            warn(f"Working tree is dirty before issue #{num} — restoring "
                 "uncommitted changes to the last commit")
            _discard_residue(proj, num, "dirty tree before issue")

        if num > 1:
            status = run_regression(proj, num)
            if status == "failed":
                # #44: a red suite gets the same treatment as a stuck worker
                # — one resolution-guided repair attempt, not an instant skip.
                # The pomodoro run skipped 11 issues on a stub-empty suite.
                source_now = gather(proj)
                if _repair_regression(proj, num, issue_text, source_now):
                    ok("Regression repaired — continuing with the issue")
                    red_streak = 0
                else:
                    red_streak += 1
                    kb.node("blocker", f"Regression failure before issue #{num}",
                            f"Previous issues left failing tests and the "
                            f"repair attempt did not fix them. "
                            f"See regression_{num}.log and "
                            f"regression_repair_{num}.txt")
                    if red_streak >= 2:
                        # The base is broken and one guided repair could not
                        # fix it — more issue attempts on a red base produce
                        # only more red bases (pomodoro run, 2026-09-06).
                        err(f"Regression stayed red after repair (streak "
                            f"{red_streak}) — halting phase 3. Manual "
                            f"intervention needed.")
                        kb.node("blocker", "Phase 3 halted: unrepairable suite",
                                "Two consecutive red suites survived their "
                                "repair attempt. Continuing would build "
                                "every remaining issue on a broken base.")
                        _discard_residue(proj, num, "red regression repair failed before halt")
                        _commit(proj, "🚧 Phase 3 halted: unrepairable suite")
                        raise SystemExit(1)
                    warn(f"Regression stayed red before issue #{num}: "
                         f"skipping it.")
                    blocked.append(num)
                    _discard_residue(proj, num, "red regression repair failed")
                    continue
            elif status == "passed":
                red_streak = 0
            elif status == "skipped" and not warned_no_tests:
                warned_no_tests = True
                warn("No test suite in project — nothing guards previous issues.")

        ctx = pre_issue(proj, num, kb, gkb)
        kb_summaries = json.dumps(ctx["kb_summaries"], separators=(",", ":"))
        principles = json.dumps(ctx["principles"], separators=(",", ":"))
        source = gather(proj)
        output = _worker(
            proj,
            EXECUTE_SKILLS,
            EXECUTE_PROMPT.format(issue=issue_text, kb=kb_summaries,
                                  principles=principles, source=source),
            issue_text, artifact=proj / f"issue_{num}_output.txt")
        # #2: a degenerate first answer (tool JSON, questions to the absent
        # human, truncation) is not an execution — unless the worker is
        # speaking protocol (CONSULT/PROXY), which _escalate handles. The
        # protocol check is fence-free: a marker quoted as an example is
        # not the worker speaking (round-7 hardening).
        spoken = text.without_fences(output)
        if not (text.CONSULT.search(spoken) or text.PROXY.search(spoken)):
            reason = text.degenerate(output)
            if reason:
                warn(f"Issue #{num}: degenerate worker output ({reason}). "
                     f"Retrying once with feedback...")
                output = _worker(
                    proj, RETRY_SKILLS,
                    f"Your last answer was rejected: {reason}. No human is "
                    f"present — never ask questions, never narrate tool "
                    f"calls. Implement and emit the protocol markers.\n\n"
                    f"Existing source files:\n{source}\n\n"
                    f"Now implement the issue:\n{issue_text}",
                    issue_text, artifact=proj / f"issue_{num}_retry_output.txt")
                spoken = text.without_fences(output)
                if (text.degenerate(output)
                        and not (text.CONSULT.search(spoken) or text.PROXY.search(spoken))):
                    err(f"Issue #{num} blocked: worker output stayed degenerate")
                    blocked.append(num)
                    kb.node("blocker", f"Issue #{num} degenerate output",
                            f"Worker never produced a usable answer: {reason}")
                    _discard_residue(proj, num, "degenerate output")
                    continue
        stuck, output = _escalate(proj, num, output, issue_text, kb_summaries,
                                   source, kb, fails, history, blocked)
        if not stuck:
            suite = run_regression(proj, num)
            if suite != "passed":
                blocked.append(num)
                kb.node("blocker", f"Issue #{num} tests not passing",
                        f"Post-issue regression verdict: {suite}")
                _discard_residue(proj, num, "post-issue tests not passing")
                continue
            ok(f"Issue #{num} executed and tested")
            post_issue(proj, num, output, kb)
            # micro-learning after every issue (the per-issue learner)
            learn.learn_issue(proj, num, issue_text, kb, gkb)
    return blocked


def _escalate(proj: Path, num: int, output: str, issue_text: str, kb_summaries: str,
              source: str, kb: Graph, fails: dict, history: dict,
              blocked: list[int]) -> tuple[bool, str]:
    """Resolve requests with bounded retries; every returned answer is checked."""
    proxy_attempts = 0

    def block(reason: str, suffix: str = "blocked") -> tuple[bool, str]:
        blocked.append(num)
        kb.node("blocker", f"Issue #{num} {suffix}", reason)
        _discard_residue(proj, num, reason)
        return True, output

    def retry(feedback: str) -> str:
        return _worker(proj, RETRY_SKILLS, feedback, issue_text,
                       artifact=proj / f"issue_{num}_retry_output.txt")

    while True:
        spoken = text.without_fences(output)
        if text.PROXY.search(spoken):
            proxy_attempts += 1
            if proxy_attempts > 2:
                return block("Worker still requesting approval after proxy retries")
            request = text.after(spoken, text.PROXY.search(spoken), 20)
            decision = run_pi(
                "consultant", PROXY_PROMPT.format(request=request, kb=kb_summaries),
                request, skills=(FACTORY_SKILLS / "human-proxy", FACTORY_SKILLS / "kb-manager"),
                cwd=proj, tools="no", artifact=proj / f"proxy_{num}_output.txt")
            kb.node("proxy_decision", f"Proxy decision for issue #{num}", decision)
            signal_text = text.without_fences(decision)
            if text.REJECTED.search(signal_text):
                feedback = f"Proxy rejected: {decision}. Try a different approach for: {issue_text}"
            elif text.APPROVED.search(signal_text) and not text.NEEDS_REVISION.search(signal_text):
                feedback = (f"Proxy APPROVED your request: {decision}\n"
                            f"Approval was granted — now implement the issue fully: {issue_text}")
            else:
                feedback = (f"Proxy did not approve. Feedback: {decision}. "
                            f"Adjust the approach and implement: {issue_text}")
            output = retry(feedback)
            continue

        stuck_at = text.CONSULT.search(spoken)
        if stuck_at:
            fails[num] = fails.get(num, 0) + 1
            fail = fails[num]
            if fail > 3:
                return block("Worker still stuck after deep diagnosis", "blocked after diagnosis")
            consult = text.after(spoken, stuck_at, 50)
            history[num] = history.get(num, "") + f"Attempt {fail}: {consult}\n"
            if fail == 3:
                diagnosis = run_pi(
                    "consultant",
                    DIAGNOSE_PROMPT.format(issue=issue_text, history=history[num], kb=kb_summaries),
                    f"Diagnose issue #{num}", skills=(
                        FACTORY_SKILLS / "consultant-protocol",
                        FACTORY_SKILLS / "human-proxy", FACTORY_SKILLS / "kb-manager"),
                    cwd=proj, tools="no", artifact=proj / f"diagnosis_{num}_output.txt")
                kb.node("consultation", f"Deep diagnosis for issue #{num}", diagnosis)
                signal_text = text.without_fences(diagnosis)
                if text.SKIP.search(signal_text) or text.CRITICAL.search(signal_text):
                    result = block("Skipped after deep diagnosis: " + diagnosis, "skipped after diagnosis")
                    if text.CRITICAL.search(signal_text):
                        (proj / "stop.md").write_text(
                            f"Issue #{num} is critical. Manual intervention needed.")
                        raise SystemExit(1)
                    return result
                output = retry(
                    f"A senior engineer did a deep diagnosis and provided this plan:\n\n"
                    f"{diagnosis}\n\nExisting source files:\n{gather(proj)}\n\n"
                    f"Now implement the issue:\n{issue_text}")
            else:
                resolution = run_pi(
                    "consultant", CONSULT_PROMPT.format(consult=consult, kb=kb_summaries),
                    consult, skills=(FACTORY_SKILLS / "consultant-protocol",
                                     FACTORY_SKILLS / "kb-manager"),
                    cwd=proj, tools="no", artifact=proj / f"consult_{num}_output.txt")
                kb.node("consultation", f"Consultation for issue #{num}", consult)
                output = retry(
                    f"A senior engineer provided this guidance:\n\n{resolution}\n\n"
                    f"Existing source files:\n{gather(proj)}\n\n"
                    f"Now implement the issue:\n{issue_text}")
            continue

        reason = text.degenerate(output)
        if reason:
            return block(f"Unusable worker answer after recovery: {reason}")
        return False, output


# ─── Phase 4: REVIEW ─────────────────────────────────────────────────────

REVIEW_PROMPT = """You are the code-reviewer persona. Follow the code-review-and-quality skill.
Review all code across 5 axes: correctness, readability, architecture, security, performance.

Reference: definition-of-done.md for exit criteria.

KB Context:
{kb}

Source files to review:
{source}

If review passes: REVIEW_PASSED: <summary>
If critical issues: REVIEW_FAILED: <issues>. List each issue with the file name and specific fix needed."""

PROXY_REVIEW_PROMPT = """You are the human-proxy. Evaluate if this review meets the Definition of Done.
Review output:
{review}
KB Context:
{kb}
Decide: APPROVED or NEEDS_REVISION — and output the decision as a line starting
with the marker. A decision line without a marker counts as NOT approved."""


def review(proj: Path, kb: Graph) -> None:
    """One fix attempt, followed by a fresh review and explicit proxy approval."""
    kb_summaries = kb.compact()
    for attempt in range(2):
        source = gather(proj)
        review_out = run_pi(
            "worker", REVIEW_PROMPT.format(kb=kb_summaries, source=source),
            "Review the code in this project", skills=REVIEW_SKILLS,
            artifact=proj / "review_output.txt", cwd=proj, tools="no")
        spoken = text.without_fences(review_out)
        passed = bool(text.REVIEW_PASSED.search(spoken)
                      and not text.REVIEW_FAILED.search(spoken))
        feedback = review_out
        if passed:
            proxy_out = run_pi(
                "consultant",
                PROXY_REVIEW_PROMPT.format(review=review_out, kb=kb_summaries),
                review_out, skills=(FACTORY_SKILLS / "human-proxy",),
                artifact=proj / "proxy_review_output.txt", cwd=proj, tools="no")
            kb.node("proxy_decision", "Proxy review approval", proxy_out)
            approval = text.without_fences(proxy_out)
            if (text.APPROVED.search(approval) and not text.REJECTED.search(approval)
                    and not text.NEEDS_REVISION.search(approval)):
                ok("Review complete")
                return
            feedback += "\nProxy feedback: " + proxy_out
        if attempt == 0:
            warn("Review not approved — one fix attempt before reviewing again")
            run_pi(
                "worker", f"Review feedback: {feedback}\n\nSource files:\n{source}\n\n"
                "Apply the fixes in files and run tests. Report what changed.",
                "Fix review issues", skills=REVIEW_SKILLS,
                artifact=proj / "review_fixes_output.txt", cwd=proj)
            # Save applied work; a commit is not an approval.
            _commit(proj, "Review fixes awaiting approval")
    kb.node("blocker", "Review not approved", feedback)
    err("Review remains unapproved after fixes; resume will retry the review")
    raise SystemExit(1)


# ─── Phase 5: VERIFY (+ mechanical runtime smoke check) ──────────────────

VERIFY_PROMPT = """You are a QA engineer. Follow the debugging-and-error-recovery skill.
Verify this project runs locally:
1. Check project type (Python, Node, HTML, etc.)
2. For HTML: check that all tags are closed, scripts are valid, CSS is well-formed
3. For Python/Node: check that entry points exist and dependencies are listed
4. If it would fail, describe the fix needed
5. Output VERIFY_PASSED: or VERIFY_FAILED:

Source files:
{source}"""

WEB_PORTS = [3000, 5173, 8000, 8080, 4000]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _detect_runnable(proj: Path):
    """(command, web_ports) — ports only for HTTP entry points; a CLI smoke
    needs no port (#42: the dead PY_PORTS list is gone, runtime_smoke
    computes its own free port)."""
    if (proj / "package.json").exists():
        return ["npm", "start"], WEB_PORTS
    for name in ("main.py", "app.py"):
        if (proj / name).exists():
            return [sys.executable, str(proj / name)], None
    # #33: single-file CLIs the bash-era detection never saw — a root-level
    # script (wordcount.py) or the planner's favorite scaffold layout
    # (<dir>/<dir>.py with a __main__ guard, macpomodoro/macpomodoro.py).
    # Only scripts that RUN something count: the guard must be non-trivial
    # (not a bare `pass`/`...` stub from a scaffold-only issue).
    for d in sorted(p for p in proj.iterdir() if p.is_dir() and p.name != "tests"):
        script = d / f"{d.name}.py"
        if script.exists() and _is_entry_point(script.read_text(errors="replace")):
            return [sys.executable, str(script)], None
    for f in sorted(proj.glob("*.py")):
        if f.name not in ("main.py", "app.py") and \
                _is_entry_point(f.read_text(errors="replace")):
            return [sys.executable, str(f)], None
    # #4: a package with __main__.py runs as `python -m <pkg>` — the layout
    # this pipeline itself generates for modern Python projects.
    for d in sorted(p for p in proj.iterdir() if p.is_dir()):
        if (d / "__main__.py").exists():
            return [sys.executable, "-m", d.name], None
    if (proj / "index.html").exists():
        return [sys.executable, "-m", "http.server", "{PORT}"], None
    return None, None


def _is_entry_point(source: str) -> bool:
    """True for a real entry point: a __main__ guard whose body does work.

    The body ends at the first dedented line — a `pass`-only guard with
    functions defined later in the file is still a scaffold stub.
    """
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if re.match(r'^if __name__\s*==\s*["\']__main__["\']\s*:\s*$', line):
            body = []
            for l in lines[i + 1:]:
                if not l.strip():
                    continue
                if len(l) - len(l.lstrip()) == 0:
                    break  # dedented: the guard block ended
                if not l.lstrip().startswith("#"):
                    body.append(l.strip())
            real = "".join(body)
            return bool(real) and real not in ("pass", "...")
    return False


GUI_TOOLKITS = ("tkinter", "PyQt", "PySide", "wxPython", "kivy", "curses",
                "cocoa", "Objective-C", "SwiftUI")


def _looks_gui(proj: Path, cmd: list[str]) -> bool:
    """True when the launched entry point's project smells like a GUI —
    #54: for those, "still running" can only mean liveness; the smoke must
    say so instead of implying the user will see anything. Best-effort by
    design: a miss is only a missing caveat, never a wrong verdict."""
    if not cmd:
        return False
    target = Path(cmd[-1])
    if not target.suffix == ".py":
        return False
    try:
        source = target.read_text(errors="replace")
    except OSError:
        return False
    return any(t in source for t in GUI_TOOLKITS)


def runtime_smoke(proj: Path) -> tuple[str, str]:
    """Launch the project locally; returns (status, detail).

    Web commands (npm start, http.server) are probed over HTTP. Every other
    entry point gets CLI semantics (#19): a clean exit 0 is success, a crash
    is failure, and a process still running after the deadline simply started
    — which is all "runs locally" means for a timer or a non-HTTP server.
    """
    cmd, ports = _detect_runnable(proj)
    if cmd is None:
        return "SKIPPED", "no runnable entry point detected"
    web = cmd[0] == "npm" or "http.server" in cmd
    port = ports[0] if ports else _free_port()
    cmd = [c.replace("{PORT}", str(port)) for c in cmd]
    # round-5: stdin=DEVNULL — a CLI that reads stdin (pipes, prompts) used to
    # inherit the terminal, hang until the deadline, and read as "PASSED".
    # #53: stderr is captured now — a bare exit != 0 must be told apart by
    # what the process said (usage vs crash), not by the code alone.
    err_pipe = subprocess.DEVNULL if web else subprocess.PIPE
    proc = subprocess.Popen(cmd, cwd=proj, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=err_pipe,
                            text=True, start_new_session=True)
    try:
        deadline = time.time() + 12
        if not web:
            while time.time() < deadline:
                if proc.poll() is not None:
                    said = (proc.stderr.read() or "") if err_pipe != subprocess.DEVNULL else ""
                    if proc.returncode == 0:
                        return "PASSED", "exited cleanly (code 0)"
                    # #53: an argv-CLI launched bare that demands its
                    # argument prints usage and exits nonzero — that is
                    # the product working as specified, not a crash. A
                    # traceback is a real crash and stays FAILED.
                    if re.search(r"(?i)\busage\b", said):
                        return "SKIPPED", (f"exited {proc.returncode} asking for "
                                           "its argument (usage on stderr) — "
                                           "smoke cannot judge a bare argv-CLI")
                    return "FAILED", f"process exited with code {proc.returncode}"
                time.sleep(0.75)
            return "PASSED", "still running after 12s (started cleanly)" + (
                # #54: liveness is all a processless smoke can prove — for
                # a GUI the window may open BEHIND others (the pomodoro
                # incident: "verified" app looked dead to the human). The
                # honest verdict says what it does NOT know.
                " — window visibility NOT checked" if _looks_gui(proj, cmd)
                else "")
        last = ""
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=1.5).read(1)
                return "PASSED", f"responded on http://127.0.0.1:{port}"
            except Exception as e:
                last = str(e)
                if proc.poll() is not None:
                    return "FAILED", f"process exited with code {proc.returncode}"
                time.sleep(0.75)
        return "FAILED", f"no response on port {port}: {last}"
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        if proc.stderr:
            proc.stderr.close()


def verify(proj: Path) -> str:
    """Run the verify checks; persist the verdict for --resume (#6)."""
    source = gather(proj)
    out = run_pi("worker", VERIFY_PROMPT.format(source=source),
                 "Verify this project runs locally",
                 skills=VERIFY_SKILLS,
                 artifact=proj / "verify_output.txt", cwd=proj, tools="no")
    try:
        status, detail = runtime_smoke(proj)
    except Exception as e:
        status, detail = "FAILED", f"error: {e}"
    log(f"Runtime smoke check: {status} — {detail}")
    with open(proj / "verify_output.txt", "a") as f:
        f.write(f"\nRUNTIME_CHECK: {status} — {detail}\n")
    # Model approval never overrides red or absent tests; model failure vetoes.
    spoken = text.without_fences(out)
    suite = run_regression(proj, 0)
    with open(proj / "verify_output.txt", "a") as f:
        f.write(f"REGRESSION_CHECK: {suite}\n")
    verdict = "VERIFY_PASSED" if (
        suite == "passed" and status != "FAILED"
        and not text.VERIFY_FAILED.search(spoken)) else "VERIFY_FAILED"
    (proj / "verify_verdict.txt").write_text(verdict + "\n")
    return verdict
