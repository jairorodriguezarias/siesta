"""End-to-end pipeline runs against a fake `pi` on PATH — no live models.

The stub logs every call to $FAKE_PI_LOG, keys off the role's model name,
--skill flags and prompt markers; FAKE_PI_SCENARIO drives the escalation
ladder, proxy flow and failure paths. SIESTA_FACTORY redirects projects/,
kb/ and skills/ into a temp copy so runs never touch the real factory, and
each test gets a unique project name so the copied global KB can't collide.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pipeline import phases

FACTORY = Path(__file__).resolve().parent.parent
STUB = r"""#!/bin/bash
# fake-pi — canned model responses for the pipeline integration tests.
printf '%s\n' "$*" >> "${FAKE_PI_LOG:-/dev/null}"

model="" prev=""
for a in "$@"; do [ "$prev" = "--model" ] && model="$a"; prev="$a"; done

case "$model" in
  planner-model)
    case "$*" in
      *"spec-driven-development"*)
        # No file writes: the model prints the document, the pipeline saves it.
        case "$FAKE_PI_SCENARIO" in
          never_spec) echo "sorry, cannot write a spec right now" ;;
          *) printf '# Spec\n\nA tiny todo CLI in Python.\nStores tasks in memory, runs offline.\n' ;;
        esac ;;
      *"planning-and-task-breakdown"*)
        printf '# Issues\n\n## Issue #1: Add hello\nWrite hello.\n\n## Issue #2: Add bye\nWrite bye.\n' ;;
      *) echo "INTENT_FINALIZED: a tiny todo cli" ;;
    esac ;;
  consultant-model)
    case "$*" in
      *"Evaluate if this review meets"*)
        case "$FAKE_PI_SCENARIO" in
          review_needs_revision) echo "NEEDS_REVISION: the CLI lacks input validation" ;;
          *) echo "APPROVED: meets the definition of done" ;;
        esac ;;
      *"A worker requests approval"*)
        case "$FAKE_PI_SCENARIO" in
          proxy_rejected) echo "REJECTED: over-engineered, use the standard library" ;;
          proxy_no_marker) echo "I am honestly not sure whether the human would approve this." ;;
          *) echo "APPROVED: aligned with the intent recorded in the KB" ;;
        esac ;;
      *"DEEP DIAGNOSIS"*)
        case "$FAKE_PI_SCENARIO" in
          diagnosis_skips) echo "DIAGNOSIS: wrong environment
RECOMMENDATION: skip
SKIP: log blocker and continue" ;;
          *) echo "DIAGNOSIS: wrong approach
RECOMMENDATION: restructure
DETAILED_PLAN: start over with a simpler plan" ;;
        esac ;;
      *) echo "RESOLUTION: split the work and use the standard library
APPROACH: take the simplest path" ;;
    esac ;;
  worker-model)
    case "$*" in
      *"QA engineer"*)
        case "$FAKE_PI_SCENARIO" in
          verify_fails) echo "VERIFY_FAILED: the entry point crashes on launch" ;;
          *) echo "VERIFY_PASSED: static verification complete" ;;
        esac ;;
      *"code-reviewer"*) echo "REVIEW_PASSED: no issues found" ;;
      *"You are the factory-learner"*)
        echo "PROJECT_LEARNING:
  Project: stub
  Actions:
    LEARNING: stub learning — detail" ;;
      *)
        case "$FAKE_PI_SCENARIO" in
          consult_once)
            case "$*" in
              *"A senior engineer provided this guidance"*)
                echo "ISSUE_OK: implemented after guidance" ;;
              *) echo "CONSULT: I am stuck.
How should I implement this?" ;;
            esac ;;
          always_consult|diagnosis_skips) echo "CONSULT: I am stuck.
How should I implement this?" ;;
          proxy_request) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
          proxy_rejected|proxy_no_marker)
            case "$*" in
              *"Proxy rejected"*|*"Proxy did not approve"*)
                echo "ISSUE_OK: implemented a simpler approach with tests included" ;;
              *) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
            esac ;;
          degenerate_once)
            case "$*" in
              *"Your last answer was rejected"*)
                echo "ISSUE_OK: implemented the module and its tests after the feedback" ;;
              *) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
            esac ;;
          degenerate_always) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
          *) echo "ISSUE_OK: implemented the change with tests; the suite passes." ;;
        esac ;;
    esac ;;
  *) echo "FAKE_PI: unexpected model '$model'" >&2; exit 3 ;;
esac
"""


class PipelineRun(unittest.TestCase):
    """Full `python3 -m pipeline` runs in a temp factory with the stub."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="siesta-int-"))
        self.idea = f"build a tiny todo cli {uuid4().hex[:6]}"
        self.name = self.idea.replace(" ", "-")
        for name in ("config", "kb", "skills"):
            shutil.copytree(FACTORY / name, self.tmp / "factory" / name)
        models = json.loads((self.tmp / "factory/config/models.json").read_text())
        for role in ("planner", "worker", "consultant"):
            models[role]["model"] = f"{role}-model"
        (self.tmp / "factory/config/models.json").write_text(json.dumps(models))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def siesta(self, *args, scenario="ok", stub=True, timeout=90):
        bin_path = self.tmp / "bin"
        if stub:
            bin_path.mkdir(exist_ok=True)
            fake_pi = bin_path / "pi"
            fake_pi.write_text(STUB)
            fake_pi.chmod(0o755)
        env = os.environ | {
            "SIESTA_FACTORY": str(self.tmp / "factory"),
            "PYTHONPATH": str(FACTORY),
            "PATH": f"{bin_path}:{os.environ['PATH']}",
            "FAKE_PI_SCENARIO": scenario,
            "FAKE_PI_LOG": str(self.tmp / "pi_calls.log"),
        }
        return subprocess.run([sys.executable, "-m", "pipeline", *args],
                              capture_output=True, text=True, env=env,
                              cwd=self.tmp, stdin=subprocess.DEVNULL,
                              timeout=timeout)

    def proj(self) -> Path:
        return self.tmp / "factory/projects" / self.name

    def kb(self, path=None) -> dict:
        path = path or f"factory/projects/{self.name}/kb/graph.json"
        return json.loads((self.tmp / path).read_text())

    def types(self, graph=None, type_="blocker"):
        graph = graph or self.kb()
        return [n["summary"] for n in graph["nodes"] if n["type"] == type_]

    def log_count(self, needle):
        log = self.tmp / "pi_calls.log"
        if not log.exists():
            return 0
        return sum(1 for line in log.read_text().splitlines() if needle in line)

    def global_learnings(self, summary: str) -> list:
        nodes = self.kb("factory/kb/global-graph.json")["nodes"]
        return [n for n in nodes if n["type"] == "learning"
                and n["summary"] == summary]

    # ─── happy path ──────────────────────────────────────────────────────

    def test_auto_happy_path_completes_every_phase(self):
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "spec.md").exists())
        # The pipeline saved the spec from the model's text output — the stub
        # never writes files, so these documents prove pipeline-side writing.
        self.assertIn("A tiny todo CLI in Python",
                      (proj / "spec.md").read_text())
        self.assertTrue((proj / "issues.md").exists())
        # narration ("# Issues") trimmed: the doc starts at the first issue
        self.assertTrue((proj / "issues.md").read_text().lstrip()
                        .startswith("## Issue #1"))
        self.assertTrue((proj / "issue_1_output.txt").exists())
        self.assertTrue((proj / "issue_2_output.txt").exists())
        self.assertTrue((proj / "learning_issue_1.txt").exists(),
                        "per-issue learning hook should run after each issue")
        self.assertIn("APPROVED", (proj / "proxy_review_output.txt").read_text())
        verify = (proj / "verify_output.txt").read_text()
        self.assertIn("VERIFY_PASSED", verify)
        self.assertIn("RUNTIME_CHECK: SKIPPED", verify)  # no runnable entry point
        self.assertEqual((proj / ".pipeline-checkpoint").read_text().strip(),
                         "complete")
        # 2 issues + 2 per-issue learnings + review + verify + project learning
        self.assertEqual(self.log_count("--model worker-model"), 7)

    def test_happy_path_kb_and_git(self):
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        expected = {"intent": 1, "spec": 1, "issue": 2, "proxy_decision": 1}
        for type_, count in expected.items():
            self.assertEqual(len(self.types(self.kb(), type_)), count,
                             f"expected {count} {type_} nodes")
        # 2 per-issue decisions + the phase-6 "project complete" decision
        self.assertEqual(len(self.types(self.kb(), "decision")), 3)
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertGreaterEqual(len(self.global_learnings(
            f"Pipeline failure: {self.name}")), 0)  # pollution-free base
        # the learner stub logged a learning to the global KB
        self.assertIn("stub learning", [n["summary"] for n in
                        self.kb("factory/kb/global-graph.json")["nodes"]])
        log = subprocess.run(["git", "-C", str(self.proj()), "log",
                              "--oneline"], capture_output=True,
                             text=True).stdout
        for msg in ("Intent captured", "Spec generated", "Plan generated",
                    "Issue #1: implemented", "Issue #2: implemented",
                    "Project verified"):
            self.assertIn(msg, log)

    # ─── escalation ladder ───────────────────────────────────────────────

    def test_consult_blocks_issue_after_failed_resolution(self):
        result = self.siesta("--auto", self.idea, scenario="always_consult")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        # The ladder runs to fail 3: two GLM resolutions, then deep diagnosis.
        self.assertTrue((proj / "consult_1_output.txt").exists())
        self.assertTrue((proj / "issue_1_retry_output.txt").exists())
        self.assertTrue((proj / "diagnosis_1_output.txt").exists())
        # The diagnosis had no SKIP marker → fed back to the worker → the
        # worker is still stuck → the issue is blocked after diagnosis.
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 blocked after diagnosis", blockers)
        self.assertIn("Issue #2 blocked after diagnosis", blockers)
        # Per issue: initial + 2 resolution retries + 1 diagnosis-feedback
        # retry = 4 worker calls; learn hooks skipped when blocked.
        # Phases 4 + 5 + project learning add 3 → 11 worker calls.
        self.assertEqual(self.log_count("--model worker-model"), 11)
        # Per issue: 2 resolutions + 1 diagnosis = 3 consultant calls,
        # plus the review proxy → 7.
        self.assertEqual(self.log_count("--model consultant-model"), 7)
        self.assertIn("2 blocked", result.stdout)
        self.assertFalse((proj / "learning_issue_1.txt").exists())

    def test_deep_diagnosis_can_skip_issue(self):
        result = self.siesta("--auto", self.idea, scenario="diagnosis_skips")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "diagnosis_1_output.txt").exists())
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 skipped after diagnosis", blockers)
        self.assertIn("Issue #2 skipped after diagnosis", blockers)
        self.assertFalse((proj / "stop.md").exists())  # SKIP, not CRITICAL
        # Per issue: initial + 2 resolution retries = 3 worker calls (no
        # diagnosis feedback for a skip); review + verify + project
        # learning add 3 → 9.
        self.assertEqual(self.log_count("--model worker-model"), 9)
        self.assertEqual(self.log_count("--model consultant-model"), 7)
        self.assertIn("2 blocked", result.stdout)

    def test_single_consultation_recovers_issue(self):
        result = self.siesta("--auto", self.idea, scenario="consult_once")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "consult_1_output.txt").exists())
        # GLM's guidance recovered the worker on the first fed-back retry:
        # no blocker, no diagnosis, issue decisions recorded.
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertFalse((proj / "diagnosis_1_output.txt").exists())
        self.assertEqual(len(self.types(self.kb(), "decision")), 3)
        self.assertIn("0 blocked", result.stdout)
        # Per issue: initial + 1 fed-back retry + the learning hook = 3
        # worker calls; review, verify and project learning add 3 → 9.
        self.assertEqual(self.log_count("--model worker-model"), 9)
        # 1 resolution per issue + the review proxy = 3.
        self.assertEqual(self.log_count("--model consultant-model"), 3)
        # recovered issues DO get the per-issue learning hook
        self.assertTrue((proj / "learning_issue_1.txt").exists())

    def test_preexisting_stop_md_halts_cleanly(self):
        proj = self.proj()
        proj.mkdir(parents=True)
        (proj / "stop.md").write_text("manual halt for test")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual((proj / ".pipeline-checkpoint").read_text().strip(),
                         "phase-2")  # halted mid-execute: phase 3 not marked
        self.assertIn("Pipeline halted by stop.md", self.types(self.kb(),
                                                               "blocker"))
        # clean stop (SystemExit 0) — no failure learning for this project
        self.assertEqual(self.global_learnings(f"Pipeline failure: "
                                               f"{self.name}"), [])
        self.assertEqual(self.log_count("--model worker-model"), 0)

    def test_proxy_approval_completes_issue(self):
        result = self.siesta("--auto", self.idea, scenario="proxy_request")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertIn("APPROVED", (proj / "proxy_1_output.txt").read_text())
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        # 2 issue-level proxies + 1 review proxy
        self.assertEqual(len(self.types(self.kb(), "proxy_decision")), 3)

    # ─── degenerate-output guard (#2) ────────────────────────────────────

    def decisions(self):
        return self.types(self.kb(), "decision")

    def test_degenerate_worker_output_blocked_not_faked(self):
        result = self.siesta("--auto", self.idea, scenario="degenerate_always")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 degenerate output", blockers)
        self.assertIn("Issue #2 degenerate output", blockers)
        # the #2 regression: garbage output must NOT become a completion
        self.assertNotIn("Issue #1 completed", self.decisions())
        self.assertFalse((self.proj() / "learning_issue_1.txt").exists())
        self.assertIn("2 blocked", result.stdout)
        # per issue: initial + 1 degenerate feedback retry = 2 worker calls,
        # no learn hooks when blocked; review + verify + project learning = 3
        self.assertEqual(self.log_count("--model worker-model"), 7)

    def test_degenerate_once_recovers_with_feedback(self):
        result = self.siesta("--auto", self.idea, scenario="degenerate_once")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertIn("0 blocked", result.stdout)
        self.assertTrue((self.proj() / "learning_issue_1.txt").exists())

    # ─── regression gating (#15) ─────────────────────────────────────────

    def test_failing_regression_gates_the_next_issue(self):
        proj = self.proj()
        proj.mkdir(parents=True)
        (proj / "pyproject.toml").write_text("[project]\nname = 'stub'\n")
        tests = proj / "tests"
        tests.mkdir()
        (tests / "test_broken.py").write_text(
            "def test_broken():\n    assert False, 'previous issue broke me'\n")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Regression failure before issue #2", blockers)
        # #15: the issue after a red suite is skipped, not built
        self.assertIn("1 blocked", result.stdout)
        self.assertFalse((proj / "issue_2_output.txt").exists())
        self.assertNotIn("Issue #2 completed", self.decisions())

    # ─── explicit-approval gates (#3) ─────────────────────────────────────

    def test_unapproved_proxy_feedback_retries_issue(self):
        # #3: hesitation is not approval — the worker gets feedback and retries
        result = self.siesta("--auto", self.idea, scenario="proxy_no_marker")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertNotIn("did not approve", result.stderr)  # recovered quietly
        # per issue: PROXY attempt + 1 feedback retry + learn hook; then
        # review + verify + project learning
        self.assertEqual(self.log_count("--model worker-model"), 9)
        # 2 issue-level proxies + 1 review proxy
        self.assertEqual(self.log_count("--model consultant-model"), 3)

    def test_proxy_rejection_retries_with_different_approach(self):
        result = self.siesta("--auto", self.idea, scenario="proxy_rejected")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn("REJECTED", (self.proj() / "proxy_1_output.txt").read_text())
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertEqual(self.log_count("--model consultant-model"), 3)

    # ─── review revision now applies fixes (#16/#18) ─────────────────────

    def test_review_revision_applies_fixes_with_tools(self):
        result = self.siesta("--auto", self.idea, scenario="review_needs_revision")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        # #16: the fix pass runs WITH write tools and its changes are committed
        fix_calls = [line for line in (self.tmp / "pi_calls.log").read_text()
                     .splitlines() if "Fix review issues" in line]
        self.assertEqual(len(fix_calls), 1)
        self.assertNotIn("--no-tools", fix_calls[0])
        log = subprocess.run(["git", "-C", str(self.proj()), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertIn("Review fixes", log)
        self.assertIn("NEEDS_REVISION", (self.proj() / "proxy_review_output.txt").read_text())

    # ─── verify verdict tells the truth (#6) ─────────────────────────────

    def test_failed_verify_is_recorded_as_unverified(self):
        result = self.siesta("--auto", self.idea, scenario="verify_fails")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertTrue(any("Project NOT verified" in b
                            for b in self.types(self.kb(), "blocker")))
        self.assertEqual((self.proj() / "verify_verdict.txt").read_text().strip(),
                         "VERIFY_FAILED")
        log = subprocess.run(["git", "-C", str(self.proj()), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertIn("UNVERIFIED", log)
        self.assertNotIn("Project verified", log)
        # a failed project still completes (issues done), only the verdict is honest
        self.assertEqual((self.proj() / ".pipeline-checkpoint").read_text().strip(),
                         "complete")

    # ─── resume ──────────────────────────────────────────────────────────

    def test_resume_skips_completed_issues(self):
        # #9: a resume must not re-run issues whose completion node is on disk
        self.siesta("--auto", self.idea)
        (self.proj() / ".pipeline-checkpoint").write_text("phase-2\n")
        (self.tmp / "pi_calls.log").write_text("")
        result = self.siesta("--auto", self.idea, scenario="always_consult")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        # no issue-executor skill calls: both completed issues were skipped
        # (the path form only — the learner prompts also list the name)
        self.assertEqual(self.log_count("skills/issue-executor/"), 0)
        # only the review proxy ran on the consultant side
        self.assertEqual(self.log_count("consultant-model"), 1)
        self.assertIn("0 blocked", result.stdout)
        self.assertEqual((self.proj() / ".pipeline-checkpoint").read_text().strip(),
                         "complete")

    def test_generated_project_has_hygiene_gitignore(self):
        # #7: `git add -A` must not commit .DS_Store/__pycache__/checkpoint
        self.siesta("--auto", self.idea)
        proj = self.proj()
        self.assertIn("__pycache__/", (proj / ".gitignore").read_text())
        files = subprocess.run(["git", "-C", str(proj), "ls-files"],
                               capture_output=True, text=True).stdout
        self.assertNotIn(".pipeline-checkpoint", files)

    def test_resume_from_phase_2_skips_interview_and_spec(self):
        self.siesta("--auto", self.idea)
        (self.proj() / ".pipeline-checkpoint").write_text("phase-2\n")
        (self.tmp / "pi_calls.log").write_text("")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        # the regression: phases 0 and 1 must NOT re-run (bash re-interviewed)
        self.assertEqual(self.log_count("interview-me"), 0)
        self.assertEqual(self.log_count("spec-driven-development"), 0)
        self.assertGreaterEqual(self.log_count("--model worker-model"), 2)
        self.assertEqual((self.proj() / ".pipeline-checkpoint")
                         .read_text().strip(), "complete")

    # ─── failure learning ────────────────────────────────────────────────

    def test_spec_failure_logs_blocker_and_learning(self):
        result = self.siesta("--auto", self.idea, scenario="never_spec")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Spec generation failed", result.stderr)
        self.assertIn("Pipeline failed", self.types(self.kb(), "blocker"))
        found = self.global_learnings(f"Pipeline failure: {self.name}")
        self.assertEqual(len(found), 1)

    def test_missing_pi_binary_still_learns(self):
        result = self.siesta("--auto", self.idea, stub=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Pipeline failed", self.types(self.kb(), "blocker"))
        found = self.global_learnings(f"Pipeline failure: {self.name}")
        self.assertEqual(len(found), 1)


class RuntimeSmoke(unittest.TestCase):
    def smoke(self, files: dict) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases.runtime_smoke(Path(d))

    def test_static_site_is_served_and_probed(self):
        status, detail = self.smoke({"index.html": "<h1>hi</h1>"})
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("127.0.0.1", detail)

    def test_crashing_entry_point_fails(self):
        status, detail = self.smoke({"main.py": "raise SystemExit(3)"})
        self.assertEqual(status, "FAILED", detail)
        self.assertIn("exited", detail)

    def test_no_entry_point_skips(self):
        status, detail = self.smoke({"notes.txt": "nothing runnable"})
        self.assertEqual(status, "SKIPPED", detail)

    def test_package_with_dunder_main_runs(self):
        # #4: `python -m <pkg>` entry points are detected and run
        status, detail = self.smoke({
            "pyproject.toml": "[project]\nname = 'pkg'\n",
            "pkg/__main__.py": "print('hello from the package')",
        })
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("exited cleanly", detail)

    def test_cli_exiting_zero_is_success(self):
        # #19: a working CLI counts as PASSED, not "process exited with code 0"
        status, detail = self.smoke({"main.py": "print('done')"})
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("exited cleanly", detail)


if __name__ == "__main__":
    unittest.main()