"""Prompt-slot discipline for the text-protocol phases.

Live runs #3 and #4: the model reads the LAST human message as the actual
request. With the idea/spec in that slot, GLM-5.2 wrote the whole program
instead of a spec, then reviewed its own code instead of planning. The data
(intent, spec) must live inside the instruction body; the final human message
must be the rigid output directive.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline import phases
from pipeline.kb import Graph

SPEC_TEXT = "# Spec\n\nA tiny caesar cipher CLI in Python, stdlib only.\n"


class PhaseSlots(unittest.TestCase):
    """phase1/phase2 must put DATA in the body and the ORDER in the user slot."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        (self.proj / "spec.md").write_text(SPEC_TEXT)
        self.kb = Graph(self.proj / "kb" / "graph.json")
        # edge() now rejects dangling ids — fixture must use a real node id
        self.n1 = self.kb.node("intent", "fixture intent node")

    def test_phase1_intent_lives_in_body_user_is_output_directive(self):
        captured = {}

        def fake(role, body, user, **kw):
            captured.update(role=role, body=body, user=user)
            return "# Spec\n\nA tiny caesar cipher CLI spec.\n"

        with patch.object(phases, "run_pi", fake):
            phases.phase1(self.proj, "caesar", "a tiny caesar cipher cli",
                          self.n1, self.kb)
        self.assertIn("a tiny caesar cipher cli", captured["body"])
        self.assertIn("spec.md", captured["user"])
        self.assertNotIn("caesar", captured["user"])

    def test_phase2_spec_lives_in_body_user_is_output_directive(self):
        captured = {}

        def fake(role, body, user, **kw):
            captured.update(body=body, user=user)
            return "## Issue #1: Add encode\n\nImplement shift encoding.\n"

        with patch.object(phases, "run_pi", fake):
            phases.phase2(self.proj, "caesar", self.n1, self.kb)
        self.assertIn("caesar cipher CLI", captured["body"])
        self.assertIn("issues.md", captured["user"])
        self.assertNotIn("caesar cipher CLI", captured["user"])

    def test_phase2_plan_prompt_forbids_zero_test_scaffolds(self):
        # #47: the pomodoro plan's scaffold issue demanded "collects zero
        # tests" — under TDD that arms the regression gate. The planner
        # prompt must demand at least one smoke test per issue.
        captured = {}

        def fake(role, body, user, **kw):
            captured.update(body=body)
            return "## Issue #1: Add encode\n\nImplement shift encoding.\n"

        with patch.object(phases, "run_pi", fake):
            phases.phase2(self.proj, "caesar", self.n1, self.kb)
        self.assertIn("NEVER an empty test file", captured["body"])
        self.assertIn("smoke test", captured["body"])

    def test_phase2_issues_saved_from_model_text(self):
        out = "## Issue #1: Add encode\n\nImplement shift encoding.\n"
        with patch.object(phases, "run_pi", lambda *a, **k: out):
            n = phases.phase2(self.proj, "caesar", self.n1, self.kb)
        self.assertEqual(n, 1)
        self.assertTrue((self.proj / "issues.md").read_text().startswith("## Issue #1"))

    def test_phase1_template_spec_gets_one_feedback_retry(self):
        # round-3: a format-valid but off-intent spec is rejected once, then
        # retried; the good retry lands in spec.md
        template = ("# Specification\n\n## Document Metadata\n"
                    "Project name: TBD\nAuthor: TBD\nStatus: Draft\n")
        good = "# Spec\n\nA tiny caesar cipher CLI in Python, stdlib only.\n"
        calls = []

        def fake(role, body, user, **kw):
            calls.append(user)
            return template if len(calls) == 1 else good

        with patch.object(phases, "run_pi", fake):
            phases.phase1(self.proj, "caesar", "a tiny caesar cipher cli",
                          self.n1, self.kb)
        self.assertEqual(len(calls), 2)
        self.assertIn("rejected", calls[1])
        self.assertIn("caesar cipher CLI", (self.proj / "spec.md").read_text())

    def test_phase1_gives_up_after_off_intent_retry(self):
        template = ("# Specification\n\n## Document Metadata\n"
                    "Project name: TBD\nAuthor: TBD\nStatus: Draft\n")
        with patch.object(phases, "run_pi", lambda *a, **k: template):
            with self.assertRaises(SystemExit):
                phases.phase1(self.proj, "caesar", "a tiny caesar cipher cli",
                              self.n1, self.kb)

    def test_phase2_wrong_header_format_gets_one_feedback_retry(self):
        # round-3: '### 1.' priority sections don't parse — retry demands
        # the exact '## Issue #N:' header
        drifted = ("# Issues\n\n## High Priority\n\n### 1. Define MVP scope\n"
                   "- Status: Open\n")
        good = "## Issue #1: Add encode\n\nImplement shift encoding.\n"
        calls = []

        def fake(role, body, user, **kw):
            calls.append(user)
            return drifted if len(calls) == 1 else good

        with patch.object(phases, "run_pi", fake):
            phases.phase2(self.proj, "caesar", self.n1, self.kb)
        self.assertEqual(len(calls), 2)
        self.assertIn("'## Issue #N: Title'", calls[1])
        self.assertTrue((self.proj / "issues.md").read_text()
                        .startswith("## Issue #1"))


class RegressionTriState(unittest.TestCase):
    """#13: 'no tests' is 'skipped', a distinct state — not a silent green."""

    def regression(self, files: dict) -> str:
        with TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases.run_regression(Path(d), 0)

    def test_no_tests_dir_is_skipped(self):
        self.assertEqual(self.regression({"notes.txt": "nothing"}), "skipped")

    def test_no_runner_manifest_is_skipped(self):
        self.assertEqual(
            self.regression({"tests/test_x.py": "def test_x():\n    pass"}),
            "skipped")

    def test_failing_suite_is_failed(self):
        self.assertEqual(self.regression({
            "pyproject.toml": "[project]\nname = 'stub'\n",
            "tests/test_broken.py": "def test_broken():\n    assert False\n",
        }), "failed")

    def test_passing_suite_is_passed(self):
        self.assertEqual(self.regression({
            "pyproject.toml": "[project]\nname = 'stub'\n",
            "tests/test_ok.py": "def test_ok():\n    assert True\n",
        }), "passed")

    def test_zero_collected_suite_is_skipped_not_failed(self):
        # #44: pytest exits 5 on "no tests ran" — a scaffold issue's empty
        # test stub must not arm the regression gate (pomodoro run, 2026-09-06)
        self.assertEqual(self.regression({
            "pyproject.toml": "[project]\nname = 'stub'\n",
            "tests/test_empty.py": "",
        }), "skipped")


class SingleFileCLIDetection(unittest.TestCase):
    """#33: the planner's scaffold layouts must be runnable for the smoke."""

    def runnable(self, files: dict):
        with TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases._detect_runnable(Path(d))

    def test_dir_dot_py_with_real_guard_is_runnable(self):
        # the pomodoro layout: macpomodoro/macpomodoro.py with real work
        files = {"macpomodoro/macpomodoro.py":
                 "def main():\n    print('tick')\n\n"
                 "if __name__ == \"__main__\":\n    main()\n"}
        cmd, _ = self.runnable(files)
        self.assertIsNotNone(cmd)
        self.assertIn("macpomodoro/macpomodoro.py", cmd[1])

    def test_dir_dot_py_stub_guard_is_not_runnable(self):
        # issue-#1 scaffold: guard with a bare pass → not a runnable app
        files = {"macpomodoro/macpomodoro.py":
                 "if __name__ == \"__main__\":\n"
                 "    # Application entry point will go here in subsequent issues.\n"
                 "    pass\n"}
        cmd, _ = self.runnable(files)
        self.assertIsNone(cmd)

    def test_root_level_cli_script_is_runnable(self):
        # the wordcount layout: a root-level wordcount.py with a real guard
        files = {"wordcount.py":
                 "if __name__ == \"__main__\":\n    print('counting')\n"}
        cmd, _ = self.runnable(files)
        self.assertIsNotNone(cmd)
        self.assertIn("wordcount.py", cmd[1])

    def test_ellipsis_stub_is_not_runnable(self):
        files = {"tool.py": "if __name__ == \"__main__\":\n    ...\n"}
        self.assertIsNone(self.runnable(files)[0])

    def test_stub_guard_with_later_functions_is_not_runnable(self):
        # the guard body ends at the first dedented line — a `pass` stub
        # with functions defined below is still a scaffold, not an app
        files = {"macpomodoro/macpomodoro.py":
                 "if __name__ == \"__main__\":\n    pass\n\n"
                 "def later():\n    print('not part of the guard')\n"}
        self.assertIsNone(self.runnable(files)[0])

    def test_guard_with_real_work_and_later_functions_is_runnable(self):
        files = {"macpomodoro/macpomodoro.py":
                 "def main():\n    print('tick')\n\n"
                 "if __name__ == \"__main__\":\n    main()\n\n"
                 "def helper():\n    pass\n"}
        cmd, _ = self.runnable(files)
        self.assertIsNotNone(cmd)


class AbandonedInterview(unittest.TestCase):
    """#45: the human leaving mid-interview gets an autonomous close-out."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        self.kb = Graph(self.proj / "kb" / "graph.json")
        (self.proj / "interview_output.txt").write_text(
            "What UI do you want for this pomodoro app?\n")

    def test_closeout_finalizes_intent_with_defaults(self):
        calls = []

        def fake(role, body, user, **kw):
            calls.append(user)
            if len(calls) == 1:
                return "What UI do you want?\n"  # abandoned interview
            return "INTENT_FINALIZED: a tiny pomodoro cli with 25/5 defaults"

        with patch.object(phases, "run_pi", fake):
            intent, _ = phases.phase0(self.proj, "pomodoro",
                                      "build a pomodoro app", False, self.kb)
        self.assertEqual(len(calls), 2)  # interview + one close-out call
        self.assertIn("Close out the interview now", calls[1])
        self.assertIn("pomodoro cli", intent)
        # the finalized close-out replaced the raw transcript on disk
        self.assertIn("INTENT_FINALIZED",
                      (self.proj / "interview_output.txt").read_text())

    def test_closeout_failure_falls_back_loudly(self):
        def fake(role, body, user, **kw):
            return "What UI do you want?\n"  # never converges

        with patch.object(phases, "run_pi", fake):
            intent, _ = phases.phase0(self.proj, "pomodoro",
                                      "build a pomodoro app", False, self.kb)
        # raw idea is the honest fallback, not a silent success
        self.assertEqual(intent, "build a pomodoro app")


class GatherBudget(unittest.TestCase):
    """#39: gather() must cap the TOTAL prompt size — 500 lines per file ×
    every source file grows the worker prompt unbounded."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)

    def _write(self, name: str, lines: int):
        p = self.proj / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(f"# line {i} of {name}" for i in range(lines)))

    def test_small_project_gathers_everything(self):
        self._write("app.py", 50)
        out = phases.gather(self.proj)
        self.assertIn("--- File: app.py ---", out)
        self.assertIn("# line 49 of app.py", out)  # whole file included
        self.assertNotIn("TRUNCATED", out)

    def test_huge_project_is_bounded_with_notice(self):
        for i in range(40):  # 40 × 500 lines ≈ 380KB — far past any budget
            self._write(f"mod_{i:02d}.py", 500)
        out = phases.gather(self.proj)
        self.assertLessEqual(len(out), phases.GATHER_BUDGET + 2_000)
        self.assertIn("TRUNCATED:", out)
        self.assertIn("files not shown", out)
        # deterministic order: the first files made it in, the tail did not
        self.assertIn("--- File: mod_00.py ---", out)
        self.assertNotIn("--- File: mod_39.py ---", out)


if __name__ == "__main__":
    unittest.main()