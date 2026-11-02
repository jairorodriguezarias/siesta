"""Recovery gates exercised through real pipeline, git, KB and pytest processes.

Only the model boundary is fake. Its writes represent tool calls, so recovery
must produce committed code as well as a plausible completion transcript.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import phases
from pipeline.__main__ import GITIGNORE
from pipeline.kb import Graph


FACTORY = Path(__file__).resolve().parent.parent
FAKE_PI = r'''import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
model = args[args.index("--model") + 1]
prompt = sys.stdin.read() or args[-1]
scenario = os.environ["RECOVERY_SCENARIO"]
log = Path(os.environ["RECOVERY_CALLS"])
calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

def answer(kind, output):
    with log.open("a") as stream:
        stream.write(json.dumps({"kind": kind, "prompt": prompt, "output": output, "args": args}) + "\n")
    print(output)
    raise SystemExit(0)

def implement():
    Path("answer.py").write_text("def answer():\n    return 42\n")
    Path("tests/test_answer.py").write_text(
        "from answer import answer\n\ndef test_answer():\n    assert answer() == 42\n")

def implement_wrong():
    Path("answer.py").write_text("def answer():\n    return 0\n")
    if os.environ["RECOVERY_SCENARIO"] == "issue_review_test_mutates":
        Path("tests/test_answer.py").write_text(
            "from pathlib import Path\nfrom answer import answer\n\n"
            "def test_answer():\n    assert answer() == 0\n"
            "    Path('answer.py').write_text('def answer(): return 9\\n')\n")
    else:
        Path("tests/test_answer.py").write_text(
            "from answer import answer\n\ndef test_answer():\n    assert answer() == 0\n")

def review_pass(summary):
    return json.dumps({"version": 1, "verdict": "pass", "summary": summary, "findings": []})

def review_finding():
    return json.dumps({"version": 1, "verdict": "findings", "summary": "Answer is incorrect.",
        "findings": [{"id": "F1", "severity": "major", "target": "R1 / answer.py",
            "evidence": "answer() returns 0 instead of 42.",
            "requested_fix": "Return 42 and cover it with a regression test."}]})

if model == "planner-model":
    answer("unexpected_planner", "Unexpected planner invocation during resume")
if "You are the factory-learner" in prompt:
    answer("learner", "PROJECT_LEARNING:\n  Project: recovery\n  Actions:\n    LEARNING: Recovery observed — bounded protocol retries")
if model == "consultant-model":
    if "Agent identity: intent-critic" in prompt:
        answer("intent_review", '{"version":1,"verdict":"pass","changes":[],"unresolved":[]}')
    if "Issue review contract:" in prompt and "Agent identity: integration-reviewer" in prompt:
        if scenario == "issue_review_repaired" and "return 42" not in Path("answer.py").read_text():
            answer("issue_review_integration", review_finding())
        if scenario in {"issue_review_repair_regresses", "issue_review_rejected"}:
            answer("issue_review_integration", review_finding())
        answer("issue_review_integration", review_pass("The active issue meets its contract."))
    if "Issue review contract:" in prompt and "Agent identity: quality-reviewer" in prompt:
        answer("issue_review_quality", review_pass("No concrete quality defects."))
    if "Agent identity: integration-reviewer" in prompt:
        if scenario == "review_failed_but_proxy_approves":
            answer("review_integration", '{"name":"bash","arguments":{"command":"ls"}}')
        if scenario == "review_empty_fix" or (
                scenario == "review_repaired" and "return 42" not in Path("answer.py").read_text()):
            answer("review_integration", review_finding())
        answer("review_integration", review_pass("Requirements and integration are sound."))
    if "Agent identity: quality-reviewer" in prompt:
        answer("review_quality", review_pass("No concrete code quality defects."))
    if "Independent design review by" in prompt:
        answer("design_review", '{"verdict":"passed","findings":[]}')
    if "Independent requirement evidence audit" in prompt:
        answer("requirements", json.dumps({"requirements": [{"id": "R1", "status": "supported",
            "tests": ["tests/test_answer.py::test_answer"], "sources": ["answer.py"],
            "reason": "The test checks the answer is 42."}], "drift": []}))
    if "Evaluate if this review meets" in prompt:
        if scenario == "review_proxy_denied":
            answer("review_proxy", "NEEDS_REVISION: answer must return 42")
        answer("review_proxy", "APPROVED: meets the recorded acceptance criteria")
    if "A worker requests approval" in prompt:
        answer("issue_proxy", "APPROVED: implement the recorded issue")
    if "DEEP DIAGNOSIS" in prompt:
        answer("diagnosis", "DIAGNOSIS: simplify the implementation\nDETAILED_PLAN: return 42")
    answer("consult", "RESOLUTION: return 42 with a regression test\nAPPROACH: use a plain function")
if "QA engineer" in prompt:
    answer("verify", "VERIFY_PASSED: the module and tests run")
if prompt.rstrip().endswith("Fix review issues"):
    if scenario == "review_empty_fix":
        answer("review_fix", "")
    if scenario == "review_repaired":
        implement()
    answer("review_fix", "ISSUE_OK: review feedback applied")
if prompt.rstrip().endswith("Fix issue review findings"):
    if scenario == "issue_review_repaired":
        implement()
        answer("issue_review_fix", "ISSUE_OK: corrected answer and regression test")
    if scenario == "issue_review_repair_regresses":
        Path("answer.py").write_text("def answer():\n    return 41\n")
        Path("tests/test_answer.py").write_text(
            "from answer import answer\n\ndef test_answer():\n    assert answer() == 42\n")
        answer("issue_review_fix", "ISSUE_OK: applied requested correction")
    if scenario == "issue_review_rejected":
        answer("issue_review_fix", "ISSUE_OK: no product change")
    answer("issue_review_fix", "ISSUE_OK: applied correction")
if "code-reviewer persona" in prompt:
    if scenario == "review_empty_fix":
        answer("review", '{"name":"bash","arguments":{"command":"ls"}}')
    if scenario == "review_failed_but_proxy_approves":
        answer("review", "REVIEW_FAILED: the implementation is incorrect")
    if scenario == "review_repaired" and "return 42" not in Path("answer.py").read_text():
        answer("review", "REVIEW_FAILED: answer returns 0 instead of 42")
    answer("review", "REVIEW_PASSED: implementation and tests agree")
if scenario.startswith("issue_review_"):
    if scenario == "issue_review_repaired":
        implement_wrong()
    else:
        implement_wrong()
    answer("execute", "ISSUE_OK: implemented active issue with tests")
if scenario.startswith("degenerate_then_"):
    previous = [call for call in calls if call["kind"] == "execute"]
    if not previous:
        answer("execute", "")
    if len(previous) == 1:
        marker = "PROXY_REQUEST" if scenario.endswith("proxy") else "CONSULT"
        answer("execute", marker + ": need guidance")
if scenario.startswith("escalate_"):
    _, route, result = scenario.split("_", 2)
    previous = [call for call in calls if call["kind"] == "execute"]
    if route == "diagnosis" and not any(call["kind"] == "diagnosis" for call in calls):
        answer("execute", "CONSULT: how should the answer be implemented?")
    if not previous:
        marker = "PROXY_REQUEST" if route == "proxy" else "CONSULT"
        answer("execute", marker + ": implement a function returning 42?")
    outputs = {"empty": "", "tool": '{"name":"bash","arguments":{"command":"ls"}}',
               "proxy": "PROXY_REQUEST: approval is still required"}
    if result in outputs:
        answer("execute", outputs[result])
implement()
answer("execute", "ISSUE_OK: implemented answer() returning 42 and its regression test")
'''


class RecoveryGates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="siesta-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.factory = self.root / "factory"
        for name in ("agents", "config", "kb", "skills"):
            shutil.copytree(FACTORY / name, self.factory / name)
        shutil.copytree(FACTORY.parent / ".agents", self.root / ".agents")
        config = self.factory / "config/models.json"
        models = json.loads(config.read_text())
        for role in ("planner", "worker", "consultant"):
            models[role]["model"] = f"{role}-model"
        config.write_text(json.dumps(models))
        self.idea = "recovery answer cli"
        self.proj = self.factory / "projects/recovery-answer-cli"
        self.proj.mkdir(parents=True)
        self.kb = Graph(self.proj / "kb/graph.json")
        self.calls_file = self.root / "calls.jsonl"
        bindir = self.root / "bin"
        bindir.mkdir()
        stub = bindir / "pi"
        stub.write_text(f"#!{sys.executable}\n" + FAKE_PI)
        stub.chmod(0o755)
        self.env = os.environ | {
            "SIESTA_FACTORY": str(self.factory),
            "PYTHONPATH": str(FACTORY),
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "RECOVERY_CALLS": str(self.calls_file),
            "SIESTA_PI_TIMEOUT": "10",
            "GIT_AUTHOR_NAME": "Recovery Test",
            "GIT_AUTHOR_EMAIL": "recovery@example.invalid",
            "GIT_COMMITTER_NAME": "Recovery Test",
            "GIT_COMMITTER_EMAIL": "recovery@example.invalid",
        }

    def git(self, *args):
        proc = subprocess.run(["git", *args], cwd=self.proj, env=self.env,
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def seed(self, checkpoint="phase-2", *, pending=True):
        (self.proj / ".gitignore").write_text(GITIGNORE)
        (self.proj / ".pipeline-idea").write_text(self.idea + "\n")
        (self.proj / ".pipeline-checkpoint").write_text(checkpoint + "\n")
        (self.proj / "interview_output.txt").write_text("INTENT_FINALIZED: " + self.idea)
        (self.proj / "spec.md").write_text("# Spec\nBuild answer() returning 42 in Python.\n\n## Acceptance criteria\n- R1: Return 42.\n")
        (self.proj / "issues.md").write_text(
            "## Issue #1: Implement answer\nR1: Return 42.\nReturn 42 with tests.\n"
            "Test strategy: Assert answer() returns 42.\nDependencies: none.\n")
        (self.proj / "requirements.txt").write_text("# Standard library only\n")
        (self.proj / "answer.py").write_text("def answer():\n    return 0\n")
        (self.proj / "tests").mkdir()
        (self.proj / "tests/test_base.py").write_text(
            "from answer import answer\n\ndef test_base_callable():\n    assert callable(answer)\n")
        self.kb.node("intent", "Intent", self.idea)
        self.kb.node("spec", "Spec", "Return 42")
        self.kb.node("issue", "Issue #1: Implement answer", "Return 42 with tests")
        if not pending:
            self.kb.node("decision", "Issue #1 completed", "Fixture implementation recorded")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-qm", "Seed resumable project")
        self.seed_commit = self.git("rev-parse", "HEAD").strip()

    def reset_case(self, checkpoint):
        # Each subcase starts from the same real committed product and KB;
        # a false completion in one case must not skip the next reproduction.
        self.git("reset", "--hard", self.seed_commit)
        self.calls_file.write_text("")
        (self.proj / ".pipeline-checkpoint").write_text(checkpoint + "\n")
        shutil.rmtree(self.proj / ".siesta", ignore_errors=True)

    def run_pipeline(self, scenario="ok"):
        return subprocess.run([sys.executable, "-m", "pipeline", "--auto", self.idea],
                              cwd=self.root, env=self.env | {"RECOVERY_SCENARIO": scenario},
                              capture_output=True, text=True, timeout=60)

    def calls(self, kind):
        if not self.calls_file.exists():
            return []
        selected = ({"review_integration", "review_quality"}
                    if kind == "review" else {kind})
        return [call for line in self.calls_file.read_text().splitlines()
                if (call := json.loads(line))["kind"] in selected]

    def summaries(self, type_):
        return [node["summary"] for node in self.kb.query(type_=type_)]

    def assert_issue_blocked(self):
        self.assertNotIn("Issue #1 completed", self.summaries("decision"))
        self.assertTrue(any("Issue #1" in summary for summary in self.summaries("blocker")))

    def test_unusable_retries_after_consultation_do_not_complete_issue(self):
        self.seed()
        for response in ("empty", "tool", "proxy"):
            with self.subTest(response=response):
                self.reset_case("phase-2")
                self.run_pipeline(f"escalate_consult_{response}")
                self.assertTrue(self.calls("consult"))
                self.assert_issue_blocked()

    def test_unusable_retries_after_proxy_do_not_complete_issue(self):
        self.seed()
        for response in ("empty", "tool", "proxy"):
            with self.subTest(response=response):
                self.reset_case("phase-2")
                self.run_pipeline(f"escalate_proxy_{response}")
                self.assertTrue(self.calls("issue_proxy"))
                self.assert_issue_blocked()

    def test_unusable_retries_after_diagnosis_do_not_complete_issue(self):
        self.seed()
        for response in ("empty", "tool", "proxy"):
            with self.subTest(response=response):
                self.reset_case("phase-2")
                self.run_pipeline(f"escalate_diagnosis_{response}")
                self.assertTrue(self.calls("diagnosis"))
                self.assert_issue_blocked()

    def test_recovery_after_consultation_commits_implemented_code(self):
        self.seed()
        result = self.run_pipeline("escalate_consult_recovered")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls("consult"))
        self.assertIn("Issue #1 completed", self.summaries("decision"))
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
        self.assertIn("assert answer() == 42", self.git("show", "HEAD:tests/test_answer.py"))

    def test_issue_review_repairs_then_rechecks_and_approves_before_completion(self):
        self.seed()
        result = self.run_pipeline("issue_review_repaired")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Issue #1 completed", self.summaries("decision"))
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
        self.assertTrue(self.calls("issue_review_integration"))
        self.assertGreaterEqual(len(self.calls("issue_review_integration")), 2)
        self.assertEqual(len(self.calls("issue_review_fix")), 1)
        session_files = list((self.proj / ".siesta/reviews").glob("issue-*.json"))
        self.assertEqual(len(session_files), 1)
        state = json.loads(session_files[0].read_text())
        self.assertEqual(state["status"], "approved")
        self.assertEqual(state["repair_count"], 1)
        self.assertTrue((self.proj / ".siesta/issue-1-repair-1.txt").exists())
        self.assertEqual(self.git("ls-files", ".siesta"), "")
        review_calls = len(self.calls("issue_review_integration"))
        again = self.run_pipeline("issue_review_repaired")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(self.calls("issue_review_integration")), review_calls,
                         "resuming a completed issue must not repeat its review")

    def test_issue_review_repair_regression_blocks_and_archives_issue(self):
        self.seed()
        with (self.proj / "issues.md").open("a") as stream:
            stream.write("\n## Issue #2: Extend answer\nAdd another behavior with tests.\n"
                         "Test strategy: Assert the new behavior.\nDependencies: #1.\n")
        self.git("add", "issues.md")
        self.git("commit", "-qm", "Add downstream issue")
        result = self.run_pipeline("issue_review_repair_regresses")
        self.assertNotIn("Issue #1 completed", self.summaries("decision"))
        self.assertNotIn("Issue #2 completed", self.summaries("decision"))
        self.assertEqual(len(self.calls("execute")), 1, "Issue #2 must not use rejected work as its base")
        self.assertIn("return 0", self.git("show", "HEAD:answer.py"))
        recovery_root = Path(self.git("rev-parse", "--absolute-git-dir").strip()) / "siesta-recovery"
        archives = list(recovery_root.glob("*-issue-1"))
        self.assertTrue(archives, f"no recovery archive was preserved; output={result.stdout} {result.stderr}")
        self.assertTrue(self.calls("issue_review_integration"))
        self.assertTrue(all("Issue #2" not in call["prompt"]
                            for call in self.calls("issue_review_integration")),
                        "review context must not expose later issue requirements")

    def test_issue_review_rejection_never_records_completion(self):
        self.seed()
        self.run_pipeline("issue_review_rejected")
        self.assertNotIn("Issue #1 completed", self.summaries("decision"))
        self.assertTrue(any("Issue #1" in item for item in self.summaries("blocker")))
        self.assertEqual(self.git("diff", "HEAD", "--", "answer.py", "tests"), "")

    def test_issue_tests_cannot_change_the_product_they_approve(self):
        self.seed()
        result = self.run_pipeline("issue_review_test_mutates")
        self.assertNotIn("Issue #1 completed", self.summaries("decision"))
        self.assertTrue(any("tests changed the product" in item
                            for item in self.summaries("blocker")))
        self.assertIn("return 0", self.git("show", "HEAD:answer.py"))
        self.assertEqual(self.git("diff", "HEAD", "--", "answer.py", "tests"), "")

    def test_extended_issue_review_invokes_both_independent_specialists(self):
        self.seed()
        (self.proj / "issues.md").write_text(
            "## Issue #1: Add authentication\nReview: extended\nR1: Return 42.\n"
            "Add authentication with tests.\nTest strategy: Assert answer() returns 42.\n"
            "Dependencies: none.\n")
        self.git("add", "issues.md")
        self.git("commit", "-qm", "Declare extended issue review")
        result = self.run_pipeline("issue_review_extended")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Issue #1 completed", self.summaries("decision"))
        self.assertTrue(self.calls("issue_review_integration"))
        self.assertTrue(self.calls("issue_review_quality"))

    def test_degenerate_retry_routes_short_consultation(self):
        self.seed()
        result = self.run_pipeline("degenerate_then_consult")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls("consult"))
        self.assertIn("Issue #1 completed", self.summaries("decision"))
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))

    def test_degenerate_retry_routes_short_proxy_request(self):
        self.seed()
        result = self.run_pipeline("degenerate_then_proxy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls("issue_proxy"))
        self.assertIn("Issue #1 completed", self.summaries("decision"))
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))

    def test_unapproved_or_unusable_review_cannot_close_review_phase(self):
        self.seed("phase-3", pending=False)
        for scenario in ("review_empty_fix", "review_proxy_denied", "review_failed_but_proxy_approves"):
            with self.subTest(scenario=scenario):
                self.reset_case("phase-3")
                self.run_pipeline(scenario)
                checkpoint = (self.proj / ".pipeline-checkpoint").read_text().strip()
                self.assertNotIn(checkpoint, ("phase-4", "phase-5", "complete"))
                self.assertFalse(any(summary.startswith("Project complete:")
                                     for summary in self.summaries("decision")))

    def test_review_repairs_are_reviewed_and_approved_before_completion(self):
        self.seed("phase-3", pending=False)
        result = self.run_pipeline("review_repaired")
        self.assertEqual(result.returncode, 0, result.stderr)
        fix_args = self.calls("review_fix")[0]["args"]
        self.assertNotIn("--no-tools", fix_args)
        self.assertTrue(any(arg.endswith("/issue-executor/") for arg in fix_args), fix_args)
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
        self.assertTrue(any(call["output"].startswith('{"version": 1, "verdict": "findings"')
                            for call in self.calls("review_integration")))
        self.assertTrue(any('"verdict": "pass"' in call["output"]
                            for call in self.calls("review_integration")))
        self.assertTrue(any('"verdict": "pass"' in call["output"]
                            for call in self.calls("review_quality")))
        self.assertTrue(any("integration-reviewer" in call["prompt"]
                            and "quality-reviewer" in call["prompt"]
                            for call in self.calls("review_proxy")))
        self.assertEqual((self.proj / ".pipeline-checkpoint").read_text().strip(), "complete")

    def test_verified_regression_repair_survives_a_blocked_next_issue(self):
        self.seed(pending=False)
        with (self.proj / "issues.md").open("a") as stream:
            stream.write("\n## Issue #2: Extend answer\nAdd another behavior with tests.\n"
                         "Test strategy: Assert the new behavior.\nDependencies: #1.\n")
        (self.proj / "tests/test_repaired.py").write_text(
            "from answer import answer\n\ndef test_repaired():\n    assert answer() == 42\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "Record red regression before next issue")
        repairs = []

        def model(role, body, user, **kwargs):
            if "regression suite is RED" in body:
                repairs.append(user)
                (self.proj / "answer.py").write_text("def answer():\n    return 42\n")
                return "REPAIR_DONE: restored the expected answer implementation"
            return ""  # The next issue cannot produce a usable answer.

        with patch.dict(os.environ, self.env), \
             patch.object(phases, "GLOBAL_KB", self.factory / "kb/global-graph.json"), \
             patch.object(phases, "run_pi", side_effect=model):
            blocked = phases.execute(self.proj, self.kb)
        self.assertEqual(blocked, [2])
        self.assertEqual(len(repairs), 1)
        self.assertNotIn("Issue #2 completed", self.summaries("decision"))
        self.assertIn("return 42", (self.proj / "answer.py").read_text())
        self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
        # The blocker updates the KB; product files must match the repaired commit.
        self.assertEqual(self.git("diff", "HEAD", "--", "answer.py", "tests"), "")

    def test_failed_repair_commit_halts_before_starting_next_issue(self):
        self.seed(pending=False)
        with (self.proj / "issues.md").open("a") as stream:
            stream.write("\n## Issue #2: Extend answer\nAdd another behavior with tests.\n"
                         "Test strategy: Assert the new behavior.\nDependencies: #1.\n")
        (self.proj / "tests/test_repaired.py").write_text(
            "from answer import answer\n\ndef test_repaired():\n    assert answer() == 42\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "Record red regression before next issue")
        hook = self.proj / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        model_calls = []

        def model(role, body, user, **kwargs):
            model_calls.append(user)
            if "regression suite is RED" in body:
                (self.proj / "answer.py").write_text("def answer():\n    return 42\n")
                return "REPAIR_DONE: restored the expected answer implementation"
            return ""

        with patch.dict(os.environ, self.env), \
             patch.object(phases, "GLOBAL_KB", self.factory / "kb/global-graph.json"), \
             patch.object(phases, "run_pi", side_effect=model):
            with self.assertRaisesRegex(RuntimeError, "repair.*uncommitted"):
                phases.execute(self.proj, self.kb)
        self.assertEqual(len(model_calls), 1, "Only the repair may run")
        self.assertIn("return 42", (self.proj / "answer.py").read_text())
        self.assertIn("return 0", self.git("show", "HEAD:answer.py"))
        self.assertNotIn("Issue #2 completed", self.summaries("decision"))

    def test_resume_retries_pending_issue_from_every_later_checkpoint(self):
        self.seed(pending=False)
        issue = ("\n## Issue #2: Finish answer\nReturn 42 and add its regression test.\n"
                 "Test strategy: Assert answer() returns 42.\nDependencies: #1.\n")
        with (self.proj / "issues.md").open("a") as stream:
            stream.write(issue)
        self.kb.node("issue", "Issue #2: Finish answer", issue)
        self.kb.node("blocker", "Issue #2 blocked after diagnosis", "Model call failed")
        self.git("add", "-A")
        self.git("commit", "-qm", "Record pending second issue")
        self.seed_commit = self.git("rev-parse", "HEAD").strip()
        for checkpoint in ("phase-3", "phase-4", "phase-5", "complete"):
            with self.subTest(checkpoint=checkpoint):
                self.reset_case(checkpoint)
                self.assertFalse((self.proj / "tests/test_answer.py").exists())
                (self.proj / "verify_verdict.txt").write_text("VERIFY_PASSED\n")
                result = self.run_pipeline()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Issue #2 completed", self.summaries("decision"))
                self.assertEqual(self.summaries("decision").count("Issue #1 completed"), 1)
                executions = self.calls("execute")
                self.assertTrue(executions)
                self.assertTrue(all(call["prompt"].rstrip().endswith(
                    ": Finish answer\nReturn 42 and add its regression test.\n"
                    "Test strategy: Assert answer() returns 42.\nDependencies: #1.")
                                    for call in executions), executions)
                self.assertFalse(self.calls("unexpected_planner"))
                self.assertTrue(self.calls("review"), "changed product requires a new review")
                self.assertTrue(self.calls("verify"), "changed product requires new verification")
                self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
                self.assertIn("0 blocked", result.stdout)


if __name__ == "__main__":
    unittest.main()
