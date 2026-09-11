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
prompt = args[-1]
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

if model == "planner-model":
    answer("unexpected_planner", "Unexpected planner invocation during resume")
if "You are the factory-learner" in prompt:
    answer("learner", "PROJECT_LEARNING:\n  Project: recovery\n  Actions:\n    LEARNING: Recovery observed — bounded protocol retries")
if model == "consultant-model":
    if "Evaluate if this review meets" in prompt:
        if scenario == "review_proxy_denied" or (
                scenario == "review_repaired" and "REVIEW_FAILED:" in prompt):
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
if "code-reviewer persona" in prompt:
    if scenario == "review_empty_fix":
        answer("review", '{"name":"bash","arguments":{"command":"ls"}}')
    if scenario == "review_failed_but_proxy_approves":
        answer("review", "REVIEW_FAILED: the implementation is incorrect")
    if scenario == "review_repaired" and "return 42" not in Path("answer.py").read_text():
        answer("review", "REVIEW_FAILED: answer returns 0 instead of 42")
    answer("review", "REVIEW_PASSED: implementation and tests agree")
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
        for name in ("config", "kb", "skills"):
            shutil.copytree(FACTORY / name, self.factory / name)
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
        (self.proj / "spec.md").write_text("# Spec\nBuild answer() returning 42 in Python.\n")
        (self.proj / "issues.md").write_text("## Issue #1: Implement answer\nReturn 42 with tests.\n")
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
        self.git("restore", f"--source={self.seed_commit}", "--staged", "--worktree", ".")
        self.calls_file.write_text("")
        (self.proj / ".pipeline-checkpoint").write_text(checkpoint + "\n")

    def run_pipeline(self, scenario="ok"):
        return subprocess.run([sys.executable, "-m", "pipeline", "--auto", self.idea],
                              cwd=self.root, env=self.env | {"RECOVERY_SCENARIO": scenario},
                              capture_output=True, text=True, timeout=60)

    def calls(self, kind):
        if not self.calls_file.exists():
            return []
        return [call for line in self.calls_file.read_text().splitlines()
                if (call := json.loads(line))["kind"] == kind]

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
        self.assertTrue(any(call["output"].startswith("REVIEW_FAILED:")
                            for call in self.calls("review")))
        self.assertTrue(any(call["output"].startswith("REVIEW_PASSED:")
                            for call in self.calls("review")))
        self.assertTrue(any("REVIEW_PASSED:" in call["prompt"]
                            for call in self.calls("review_proxy")))
        self.assertEqual((self.proj / ".pipeline-checkpoint").read_text().strip(), "complete")

    def test_verified_regression_repair_survives_a_blocked_next_issue(self):
        self.seed(pending=False)
        with (self.proj / "issues.md").open("a") as stream:
            stream.write("\n## Issue #2: Extend answer\nAdd another behavior with tests.\n")
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
            stream.write("\n## Issue #2: Extend answer\nAdd another behavior with tests.\n")
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
        issue = "\n## Issue #2: Finish answer\nReturn 42 and add its regression test.\n"
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
                    ": Finish answer\nReturn 42 and add its regression test.")
                                    for call in executions), executions)
                self.assertFalse(self.calls("unexpected_planner"))
                self.assertTrue(self.calls("review"), "changed product requires a new review")
                self.assertTrue(self.calls("verify"), "changed product requires new verification")
                self.assertIn("return 42", self.git("show", "HEAD:answer.py"))
                self.assertIn("0 blocked", result.stdout)


if __name__ == "__main__":
    unittest.main()
