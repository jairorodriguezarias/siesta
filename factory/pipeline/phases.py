"""Pipeline phases 0-7: intent, spec, plan, execute, review, verify, done.

Every model call keeps the bash version's prompts and skills verbatim so a
run behaves identically, minus four latent bash bugs fixed along the way:
anchored markers, first-dash learning split, monotonic resume, single
issue count. See also pipeline/text.py for the parser side.
"""
import json
import os
import signal
import socket
import subprocess
import sys
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
    for f in sorted(proj.rglob("*")):
        parts = set(f.relative_to(proj).parts)
        if ".git" in parts or "kb" in parts or f.name in (
                ".DS_Store", ".pipeline-checkpoint"):
            continue
        if f.is_file():
            yield f


def gather(proj: Path) -> str:
    parts = []
    for f in _project_files(proj):
        if f.suffix.lstrip(".") not in SOURCE_EXTS:
            continue
        content = text.head(f.read_text(errors="replace"), 500)
        parts.append(f"\n\n--- File: {f.relative_to(proj)} ---\n{content}")
    return "".join(parts)


def _git(proj: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=proj, capture_output=True)


def _commit(proj: Path, msg: str) -> None:
    _git(proj, "add", "-A")
    _git(proj, "commit", "-m", msg)


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


def post_issue(proj: Path, n: int, out: Path, kb: Graph) -> str:
    body = text.head(out.read_text(), 200) if out.exists() else ""
    node_id = kb.node("decision", f"Issue #{n} completed", body)
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
        # #12: the raw idea is a fallback, not a success — say it loudly.
        warn("Interview ended without INTENT_FINALIZED — falling back to the raw idea")
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
a SPECIFICATION DOCUMENT only."""

# The final human message is the actual request (runs #3/#4: the model obeys
# the last turn, so the order lives here and the data lives in the body).
SPEC_DIRECTIVE = ("This is not a coding request — it is a documentation task. "
                  "You have NO TOOLS. Output ONLY the complete content of "
                  "spec.md as your final message. Do NOT write code.")


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
criteria, dependencies. Keep issues small and atomic. Do NOT write code —
output the plan document only."""

PLAN_DIRECTIVE = ("This is not a code review request — it is a planning task. "
                  "You have NO TOOLS. Output ONLY the complete content of "
                  "issues.md as your final message. Do NOT write code.")

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


def run_regression(proj: Path, n: int) -> str:
    """'passed' | 'failed' | 'skipped'. Skipped (no tests, no runner) is a
    distinct state — #13: absence of tests must not read as 'green'."""
    if not (proj / "tests").is_dir():
        return "skipped"
    runner = next(((m, c) for m, c in RUNNERS if (proj / m).exists()), None)
    if runner is None:
        log("No known test runner found, skipping regression")
        return "skipped"
    cmd = runner[1]
    log("Running regression suite (all previous tests)...")
    proc = subprocess.run(cmd, cwd=proj, capture_output=True, text=True)
    (proj / f"regression_{n}.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        err(f"Regression suite FAILED before issue #{n}.")
        return "failed"
    return "passed"


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


RETRY_SKILLS = (SKILLS / "incremental-implementation",
                SKILLS / "test-driven-development")


def _worker(proj: Path, skills, body, issue_text, artifact: Path | None = None):
    return run_pi("worker", body, issue_text, skills=skills,
                  thinking=WORKER_THINKING, cwd=proj, artifact=artifact)


def execute(proj: Path, kb: Graph) -> list[int]:
    """Run every issue; return the numbers that stayed blocked."""
    issues = dict(text.split_issues((proj / "issues.md").read_text()))
    log(f"Found {len(issues)} issues to execute")
    gkb = Graph(GLOBAL_KB)
    blocked, fails, history = [], {}, {}
    warned_no_tests = False
    for num in sorted(issues):
        if (proj / "stop.md").exists():
            warn("stop.md detected! Halting pipeline.")
            kb.node("blocker", "Pipeline halted by stop.md",
                    (proj / "stop.md").read_text())
            raise SystemExit(0)
        log(f"Executing issue #{num}...")
        issue_text = issues[num]

        if num > 1:
            status = run_regression(proj, num)
            if status == "failed":
                # #15: the regression suite is a guard, not a witness —
                # never build the next issue on a broken base.
                kb.node("blocker", f"Regression failure before issue #{num}",
                        f"Previous issue broke existing tests. "
                        f"See regression_{num}.log")
                warn(f"Regression failed before issue #{num}: skipping it.")
                blocked.append(num)
                continue
            if status == "skipped" and not warned_no_tests:
                warned_no_tests = True
                warn("No test suite in project — nothing guards previous issues.")

        ctx = pre_issue(proj, num, kb, gkb)
        kb_summaries = json.dumps(ctx["kb_summaries"], separators=(",", ":"))
        principles = json.dumps(ctx["principles"], separators=(",", ":"))
        source = gather(proj)
        output = _worker(
            proj,
            (SKILLS / "incremental-implementation", SKILLS / "test-driven-development",
             SKILLS / "debugging-and-error-recovery", FACTORY_SKILLS / "issue-executor",
             FACTORY_SKILLS / "kb-manager"),
            EXECUTE_PROMPT.format(issue=issue_text, kb=kb_summaries,
                                  principles=principles, source=source),
            issue_text, artifact=proj / f"issue_{num}_output.txt")
        # #2: a degenerate first answer (tool JSON, questions to the absent
        # human, truncation) is not an execution — unless the worker is
        # speaking protocol (CONSULT/PROXY), which _escalate handles.
        if not (text.CONSULT.search(output) or text.PROXY.search(output)):
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
                if text.degenerate(output):
                    err(f"Issue #{num} blocked: worker output stayed degenerate")
                    blocked.append(num)
                    kb.node("blocker", f"Issue #{num} degenerate output",
                            f"Worker never produced a usable answer: {reason}")
                    continue
        stuck = _escalate(proj, num, output, issue_text, kb_summaries, source,
                          kb, fails, history, blocked)
        if not stuck:
            ok(f"Issue #{num} executed")
            post_issue(proj, num, proj / f"issue_{num}_output.txt", kb)
            # micro-learning after every issue (the per-issue learner)
            learn.learn_issue(proj, num, issue_text, kb, gkb)
    return blocked


def _escalate(proj: Path, num: int, output: str, issue_text: str, kb_summaries: str,
              source: str, kb: Graph, fails: dict, history: dict,
              blocked: list[int]) -> bool:
    """Walk the stuck protocol. Returns True if the issue needs no post-work."""
    def _retry(feedback: str) -> str:
        return _worker(proj, RETRY_SKILLS, feedback, issue_text,
                       artifact=proj / f"issue_{num}_retry_output.txt")

    if text.PROXY.search(output):
        log(f"Worker requesting proxy approval for issue #{num}...")
        request = text.after(output, text.PROXY.search(output), 20)
        decision = run_pi("consultant", PROXY_PROMPT.format(request=request, kb=kb_summaries),
                          request, skills=(FACTORY_SKILLS / "human-proxy",
                                           FACTORY_SKILLS / "kb-manager"), cwd=proj, tools="no",
                          artifact=proj / f"proxy_{num}_output.txt")
        kb.node("proxy_decision", f"Proxy decision for issue #{num}", decision)
        if text.APPROVED.search(decision):
            log("Proxy explicitly approved — continuing with the approach")
        elif text.REJECTED.search(decision):
            warn("Proxy rejected, retrying with a different approach...")
            output = _retry(
                f"Proxy rejected: {decision}. Try a different approach for: {issue_text}")
        else:
            # #3: fail-closed gate — NEEDS_REVISION, hesitation or garbage is
            # NOT approval; the worker gets the feedback and retries.
            warn("Proxy did not explicitly approve — retrying with feedback...")
            output = _retry(
                f"Proxy did not approve. Feedback: {decision}. "
                f"Adjust the approach and implement: {issue_text}")

    # Escalation ladder: 2 resolution-guided retries, then the fail-3 deep
    # diagnosis (documented in README/AGENTS.md; unreachable in bash).
    stuck_at = text.CONSULT.search(output)
    while stuck_at:
        fails[num] = fails.get(num, 0) + 1
        fail = fails[num]
        warn(f"Worker stuck (attempt {fail}), consulting the local model...")
        consult = text.after(output, stuck_at, 50)
        history[num] = history.get(num, "") + f"Attempt {fail}: {consult}\n"
        if fail >= 3:
            warn(f"3 failures on issue #{num}. Triggering deep diagnosis...")
            diagnosis = run_pi(
                "consultant",
                DIAGNOSE_PROMPT.format(issue=issue_text, history=history[num], kb=kb_summaries),
                # thinking="high" is a GLM feature — qwen2.5-coder 400s on it.
                f"Diagnose issue #{num}", skills=(
                    FACTORY_SKILLS / "consultant-protocol",
                    FACTORY_SKILLS / "human-proxy", FACTORY_SKILLS / "kb-manager"),
                cwd=proj, tools="no", artifact=proj / f"diagnosis_{num}_output.txt")
            kb.node("consultation", f"Deep diagnosis for issue #{num}", diagnosis)
            if text.SKIP.search(diagnosis):
                err(f"Issue #{num} SKIPPED after deep diagnosis")
                blocked.append(num)
                kb.node("blocker", f"Issue #{num} skipped after diagnosis", diagnosis)
                if text.CRITICAL.search(diagnosis):
                    (proj / "stop.md").write_text(
                        f"Issue #{num} is critical and cannot be skipped. "
                        "Manual intervention needed.")
                    err("CRITICAL: stop.md created. Pipeline will halt.")
                    raise SystemExit(0)  # per AGENTS.md: CRITICAL halts the pipeline
                return True
            log("Diagnosis provided, feeding back to worker...")
            output = _retry(
                f"A senior engineer did a deep diagnosis and provided this plan:\n\n"
                f"{diagnosis}\n\nExisting source files:\n{source}\n\n"
                f"Now implement the issue:\n{issue_text}")
            if text.CONSULT.search(output):
                err(f"Issue #{num} blocked after diagnosis")
                blocked.append(num)
                kb.node("blocker", f"Issue #{num} blocked after diagnosis",
                        "Worker still stuck after deep diagnosis")
                return True
            break  # recovered after diagnosis
        resolution = run_pi(
            "consultant", CONSULT_PROMPT.format(consult=consult, kb=kb_summaries),
            consult, skills=(FACTORY_SKILLS / "consultant-protocol",
                             FACTORY_SKILLS / "kb-manager"), cwd=proj, tools="no",
            artifact=proj / f"consult_{num}_output.txt")
        kb.node("consultation", f"Consultation for issue #{num}", consult)
        log("Consultant resolved, feeding back to worker...")
        output = _retry(
            f"A senior engineer provided this guidance:\n\n{resolution}\n\n"
            f"Existing source files:\n{source}\n\n"
            f"Now implement the issue:\n{issue_text}")
        # still CONSULT → the loop escalates (fail 2, then the fail-3 diagnosis)
        stuck_at = text.CONSULT.search(output)
    # A stuck round that recovered still gets the post hooks.
    return False


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
    kb_summaries = kb.compact()
    source = gather(proj)
    review_out = run_pi("worker", REVIEW_PROMPT.format(kb=kb_summaries, source=source),
                        "Review the code in this project",
                        skills=(SKILLS / "code-review-and-quality",
                                SKILLS / "code-simplification"),
                        artifact=proj / "review_output.txt", cwd=proj)
    if not (text.REVIEW_PASSED.search(review_out)
            or text.REVIEW_FAILED.search(review_out)):
        warn("Review output has no REVIEW_PASSED/REVIEW_FAILED marker")
    proxy_out = run_pi("consultant",
                       PROXY_REVIEW_PROMPT.format(review=review_out, kb=kb_summaries),
                       review_out, skills=(FACTORY_SKILLS / "human-proxy",),
                       artifact=proj / "proxy_review_output.txt", cwd=proj, tools="no")
    kb.node("proxy_decision", "Proxy review approval", proxy_out)
    if not text.APPROVED.search(proxy_out):
        # #3/#18: approval requires an explicit line-start marker —
        # NEEDS_REVISION, hesitation or garbage all mean "fix it", never "pass".
        warn("Proxy did not explicitly approve the review — fixing...")
        # #16: this pass has write tools (like the execute phase) so the fixes
        # actually land in the files, and are committed afterwards.
        fixes = run_pi("worker", f"Proxy requested: {proxy_out}.\n\nSource files:\n{source}\n\n"
                       "Fix the issues now. Output the corrected file contents.",
                       "Fix review issues",
                       skills=(SKILLS / "code-review-and-quality", SKILLS / "code-simplification"),
                       artifact=proj / "review_fixes_output.txt", cwd=proj)
        if text.degenerate(fixes):
            warn("Review-fix output looks degenerate — fixes may not have been applied")
        _commit(proj, "🔧 Review fixes: apply proxy-requested revisions")
    ok("Review complete")


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
PY_PORTS = [5000, 8000, 3000, 8080]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _detect_runnable(proj: Path):
    if (proj / "package.json").exists():
        return ["npm", "start"], WEB_PORTS
    for name in ("main.py", "app.py"):
        if (proj / name).exists():
            return [sys.executable, str(proj / name)], PY_PORTS
    if (proj / "index.html").exists():
        return [sys.executable, "-m", "http.server", "{PORT}"], None
    return None, None


def runtime_smoke(proj: Path) -> tuple[str, str]:
    """Launch the project locally and probe HTTP. returns (status, detail)."""
    cmd, ports = _detect_runnable(proj)
    if cmd is None:
        return "SKIPPED", "no runnable entry point detected"
    port = ports[0] if ports else _free_port()
    cmd = [c.replace("{PORT}", str(port)) for c in cmd]
    proc = subprocess.Popen(cmd, cwd=proj, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.time() + 12
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


def verify(proj: Path) -> str:
    """Run the verify checks; persist the verdict for --resume (#6)."""
    verdict = _verify(proj)
    (proj / "verify_verdict.txt").write_text(verdict + "\n")
    return verdict


def _verify(proj: Path) -> str:
    source = gather(proj)
    out = run_pi("worker", VERIFY_PROMPT.format(source=source),
                 "Verify this project runs locally",
                 skills=(SKILLS / "test-driven-development",
                         SKILLS / "debugging-and-error-recovery"),
                 artifact=proj / "verify_output.txt", cwd=proj, tools="no")
    try:
        status, detail = runtime_smoke(proj)
    except Exception as e:  # fail-open: a broken check never halts the pipeline
        status, detail = "SKIPPED", f"error: {e}"
    log(f"Runtime smoke check: {status} — {detail}")
    with open(proj / "verify_output.txt", "a") as f:
        f.write(f"\nRUNTIME_CHECK: {status} — {detail}\n")
    # #11: with no protocol marker, a degenerate body (tool JSON / questions
    # to the absent human) is not a verdict — only the mechanical checks may
    # decide then. An explicit marker stays the primary signal.
    has_marker = bool(text.VERIFY_PASSED.search(out) or text.VERIFY_FAILED.search(out))
    reason = None if has_marker else text.degenerate(out)
    if reason:
        warn(f"Verify output is degenerate ({reason}) — using the mechanical fallback only")
    if has_marker:
        # Primary signal: the protocol marker (and smoke must not have failed).
        return "VERIFY_PASSED" if (
            text.VERIFY_PASSED.search(out) and status != "FAILED") else "VERIFY_FAILED"
    # Model drifted (no marker, or degenerate — tool-speak in the live run):
    # decide from the regression suite if there is one, else fail.
    log("No usable VERIFY signal — falling back to the regression suite")
    if not (proj / "tests").is_dir():
        return "VERIFY_FAILED"
    return "VERIFY_PASSED" if (run_regression(proj, 0) == "passed"
                               and status != "FAILED") else "VERIFY_FAILED"