"""Prompt-slot discipline for the text-protocol phases.

Live runs #3 and #4: the model reads the LAST human message as the actual
request. With the idea/spec in that slot, GLM-5.2 wrote the whole program
instead of a spec, then reviewed its own code instead of planning. The data
(intent, spec) must live inside the instruction body; the final human message
must be the rigid output directive.
"""
import subprocess
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

    def test_phase2_returns_the_issue_count(self):
        # #42: the count is phase2's contract with its callers — the
        # orchestrator logs it instead of ignoring the return value.
        good = ("## Issue #1: Add encode\n\nImplement shift encoding.\n\n"
                "## Issue #2: Add decode\n\nImplement shift decoding.\n")

        def fake(role, body, user, **kw):
            return good

        with patch.object(phases, "run_pi", fake):
            count = phases.phase2(self.proj, "caesar", self.n1, self.kb)
        self.assertEqual(count, 2)


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


class RuntimeSmoke(unittest.TestCase):
    """#53: a bare argv-CLI's usage-exit is the product working as
    specified — SKIPPED with a reason, never FAILED."""

    def smoke(self, files: dict) -> tuple[str, str]:
        with TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases.runtime_smoke(Path(d))

    def test_argv_cli_usage_exit_is_skipped(self):
        # the exact run-#25 shape: spec demands `python wordcount.py <file>`
        status, detail = self.smoke({
            "wordcount.py":
                "import sys\n\n"
                "def main():\n"
                "    if len(sys.argv) != 2:\n"
                "        print('Error: No file path provided. Usage: "
                "python wordcount.py <filepath>', file=sys.stderr)\n"
                "        sys.exit(1)\n"
                "    print(open(sys.argv[1]).read())\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"})
        self.assertEqual(status, "SKIPPED")
        self.assertIn("usage", detail.lower())

    def test_crashing_cli_stays_failed(self):
        # a real traceback must never read as "could not judge"
        status, detail = self.smoke({
            "wordcount.py":
                "if __name__ == \"__main__\":\n"
                "    1 / 0\n"})
        self.assertEqual(status, "FAILED")
        self.assertIn("code 1", detail)

    def test_clean_cli_exit_is_passed(self):
        status, detail = self.smoke({
            "wordcount.py":
                "if __name__ == \"__main__\":\n    print('ok')\n"})
        self.assertEqual(status, "PASSED")
        self.assertIn("exited cleanly", detail)

    def test_gui_still_running_says_visibility_not_checked(self):
        # #54: "still running" for a GUI only proves the process lives —
        # the smoke can never see a window (the pomodoro incident: Tk
        # opened BEHIND other windows and the "verified" app looked dead).
        # The honest verdict must say what it does NOT know. Keep the GUI
        # import lazy: this tests source classification, not installed Tk.
        status, detail = self.smoke({
            "pomodoro_app.py":
                "import time\n"
                "def create_window():\n"
                "    import tkinter as tk\n"
                "    return tk.Tk()\n\n"
                "if __name__ == \"__main__\":\n"
                "    time.sleep(300)\n"})
        self.assertEqual(status, "PASSED")
        self.assertIn("still running", detail)
        self.assertIn("window visibility NOT checked", detail)

    def test_plain_still_running_keeps_old_detail(self):
        # a non-GUI long-runner (a timer daemon) needs no GUI caveat
        status, detail = self.smoke({
            "timer.py":
                "import time\n\n"
                "if __name__ == \"__main__\":\n"
                "    time.sleep(300)\n"})
        self.assertEqual(status, "PASSED")
        self.assertNotIn("visibility", detail)


class InterviewDialog(unittest.TestCase):
    """The interview is a python-mediated dialog: one model turn per call,
    the human answers in the terminal, and both sides become evidence.
    (#55: the single streamed pi call never produced a real exchange.)"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        self.kb = Graph(self.proj / "kb" / "graph.json")
        self.answers = []

    def dialog(self, run_pi_fake, answers):
        self.answers = answers
        with patch.object(phases, "run_pi", run_pi_fake), \
                patch.object(phases, "_read_answer",
                             side_effect=list(answers)):
            return phases.phase0(self.proj, "pomodoro",
                                 "build a pomodoro app", False, self.kb)

    def test_real_dialog_confirms_and_records_both_sides(self):
        model_turns = [
            "Q: Menu bar app, standalone window, or terminal CLI?\n"
            "GUESS: menu bar app — 'in my Mac' usually means always-visible.",
            "INTENT_FINALIZED: A menu-bar pomodoro timer for macOS with "
            "25/5 cycles, notifications, stdlib only.",
        ]

        def fake(role, body, user, **kw):
            return model_turns.pop(0)

        intent, _ = self.dialog(fake, ["menu bar app please",
                                       "yes"])
        self.assertIn("menu-bar pomodoro", intent)
        saved = (self.proj / "interview_output.txt").read_text()
        self.assertIn("A: menu bar app please", saved)
        self.assertIn("INTENT_FINALIZED", saved)
        self.assertEqual(len(model_turns), 0)   # every model turn consumed

    def test_refinement_round_trips_into_the_next_attempt(self):
        model_turns = [
            "Q: What UI?\nGUESS: terminal CLI.",
            "INTENT_FINALIZED: A terminal pomodoro CLI.",
            "INTENT_FINALIZED: A menu-bar pomodoro timer for macOS, "
            "per the human's correction.",
        ]
        calls = []

        def fake(role, body, user, **kw):
            calls.append((body, user))
            return model_turns.pop(0)

        intent, _ = self.dialog(fake, ["terminal",
                                       "no — menu bar, not terminal",
                                       "yes"])
        self.assertIn("menu-bar pomodoro", intent)
        self.assertIn("A (refinement): no — menu bar, not terminal",
                      (self.proj / "interview_output.txt").read_text())
        self.assertIn("Refine", calls[2][1])   # the directive said refine

    def test_premature_intent_gets_one_forced_question(self):
        # the landing-page failure: INTENT_FINALIZED with zero questions
        # is the assumption trap — one retry must force a real question
        model_turns = [
            "INTENT_FINALIZED: A landing page replica, sections as assumed.",
            "Q: Should the hero show the pipeline diagram?\n"
            "GUESS: yes, it is the selling point.",
            "INTENT_FINALIZED: A landing page with the pipeline hero.",
        ]

        def fake(role, body, user, **kw):
            return model_turns.pop(0)

        intent, _ = self.dialog(fake, ["yes", "yes"])
        self.assertIn("pipeline hero", intent)
        saved = (self.proj / "interview_output.txt").read_text()
        self.assertIn("rejected turn", saved)    # the trap kept as evidence

    def test_premature_intent_twice_goes_to_closeout(self):
        def fake(role, body, user, **kw):
            if "Close out the interview now" in user:
                return "INTENT_FINALIZED: a tiny pomodoro cli with defaults"
            return "INTENT_FINALIZED: I will just assume everything."

        intent, _ = self.dialog(fake, ["yes"] * 5)
        # the raw assumption never entered the transcript; close-out ran
        self.assertIn("pomodoro cli", intent)
        self.assertNotIn("just assume everything", intent)

    def test_degenerate_turn_then_question_recovers(self):
        model_turns = [
            '{"name": "bash", "arguments": {"command": "ls"}}',
            "Q: GUI or CLI?\nGUESS: CLI.",
            "INTENT_FINALIZED: A pomodoro CLI with sound alerts.",
        ]
        directives = []

        def fake(role, body, user, **kw):
            directives.append(user)
            return model_turns.pop(0)

        intent, _ = self.dialog(fake, ["cli please", "yes"])
        self.assertIn("pomodoro CLI", intent)
        # the degenerate turn got exactly one feedback retry
        self.assertIn("not a question", directives[1])
        self.assertLessEqual(len(directives), 3)

    def test_auto_answer_delegates_to_closeout(self):
        model_turns = ["Q: What UI?\nGUESS: terminal."]
        closeout_bodies = []

        def fake(role, body, user, **kw):
            if "Close out the interview now" in user:
                closeout_bodies.append(body)
                return "INTENT_FINALIZED: a pomodoro cli with sensible defaults"
            return model_turns.pop(0)

        intent, _ = self.dialog(fake, ["auto"])
        self.assertIn("pomodoro cli", intent)
        # the delegation was recorded in the transcript the close-out saw
        self.assertTrue(any("delegated the remaining decisions" in b
                            for b in closeout_bodies))
        saved = (self.proj / "interview_output.txt").read_text()
        self.assertIn("INTENT_FINALIZED", saved)

    def test_eof_mid_dialog_goes_to_closeout(self):
        model_turns = ["Q: What UI?\nGUESS: terminal."]

        def fake(role, body, user, **kw):
            if "Close out the interview now" in user:
                return "INTENT_FINALIZED: a pomodoro cli with sensible defaults"
            return model_turns.pop(0)

        class _EOF:
            def strip(self):
                raise EOFError

        with patch.object(phases, "run_pi", fake), \
                patch.object(phases, "_read_answer", return_value=_EOF()):
            intent, _ = phases.phase0(self.proj, "pomodoro",
                                      "build a pomodoro app", False, self.kb)
        self.assertIn("pomodoro cli", intent)


class AbandonedInterview(unittest.TestCase):
    """#45: a dialog that ends without INTENT_FINALIZED gets an autonomous
    close-out. Here the model goes silent on every turn (degenerate ×2),
    so the stale on-disk transcript survives untouched and phase 0's
    residual gate — not the dialog loop — must close it out."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        self.kb = Graph(self.proj / "kb" / "graph.json")
        (self.proj / "interview_output.txt").write_text(
            "Q: What UI do you want for this pomodoro app?\n"
            "GUESS: menu bar, it lives in the corner.\n")

    def dialog_run(self, fake):
        # EOF on read: this session has no human at the terminal
        with patch.object(phases, "run_pi", fake), \
                patch.object(phases, "_read_answer",
                             side_effect=EOFError):
            return phases.phase0(self.proj, "pomodoro",
                                 "build a pomodoro app", False, self.kb)

    def test_silent_dialog_closeout_finalizes_intent_with_defaults(self):
        calls = []

        def fake(role, body, user, **kw):
            calls.append(user)
            if "Close out the interview now" in user:
                return "INTENT_FINALIZED: a tiny pomodoro cli with 25/5 defaults"
            return ""                          # the model goes silent

        intent, _ = self.dialog_run(fake)
        self.assertEqual(len(calls), 3)  # two silent turns, then close-out
        self.assertIn("Close out the interview now", calls[2])
        self.assertIn("pomodoro cli", intent)
        # the finalized close-out replaced the raw transcript on disk
        self.assertIn("INTENT_FINALIZED",
                      (self.proj / "interview_output.txt").read_text())

    def test_closeout_failure_falls_back_loudly(self):
        def fake(role, body, user, **kw):
            return "sorry, I cannot decide"  # never converges

        intent, _ = self.dialog_run(fake)
        # raw idea is the honest fallback, not a silent success
        self.assertEqual(intent, "build a pomodoro app")


class RootLevelSuiteDetection(unittest.TestCase):
    """#50: a root-level test suite (the pomodoro layout) is a suite — the
    gate must not say 'no suite' while real tests sit at the root."""

    def regression(self, files: dict) -> str:
        with TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases.run_regression(Path(d), 0)

    def test_root_passing_suite_is_passed(self):
        # pomodoro layout: test file at the root, no tests/ dir, no manifest
        self.assertEqual(self.regression({
            "app.py": "def add(a, b):\n    return a + b\n",
            "test_app.py": "from app import add\n"
                           "def test_add():\n    assert add(1, 2) == 3\n",
        }), "passed")

    def test_root_failing_suite_is_failed(self):
        # the #49 evidence: residue deleted format_time while the root
        # test still imports it — pytest collection fails, and that
        # must read as a red suite, not as 'no suite'
        self.assertEqual(self.regression({
            "app.py": "def other():\n    pass\n",
            "test_app.py": "from app import format_time\n"
                           "def test_nothing():\n    assert True\n",
        }), "failed")

    def test_root_empty_suite_is_skipped(self):
        # #44 preserved: a zero-collected suite is absence, never red
        self.assertEqual(self.regression({
            "app.py": "x = 1\n",
            "test_empty.py": "",
        }), "skipped")

    def test_manifest_plus_root_tests_runs_both(self):
        # both suites exist → both run; a red one fails the gate
        self.assertEqual(self.regression({
            "requirements.txt": "pytest\n",
            "test_root.py": "def test_r():\n    assert True\n",
            "tests/test_ok.py": "def test_ok():\n    assert True\n",
        }), "passed")


class BlockedIssueResidue(unittest.TestCase):
    """#49: a blocked issue's uncommitted work is discarded so the base
    stays honest — the residue of pomodoro #3 broke pytest collection."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.proj,
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.proj), "config",
                        "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(self.proj), "config",
                        "user.name", "t"], capture_output=True)
        from pipeline.__main__ import GITIGNORE
        (self.proj / ".gitignore").write_text(GITIGNORE)
        (self.proj / "app.py").write_text("def format_time(s):\n    return s\n")
        (self.proj / "test_app.py").write_text(
            "from app import format_time\n"
            "def test_fmt():\n    assert format_time('x') == 'x'\n")
        subprocess.run(["git", "add", "-A"], cwd=self.proj, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"],
                       cwd=self.proj, capture_output=True)

    def residue(self):
        # the pomodoro-#3 shape: modification that deletes committed work
        (self.proj / "app.py").write_text("def phase_machine():\n    pass\n")

    def test_discard_restores_the_committed_base(self):
        self.residue()
        phases._discard_residue(self.proj, 3, "degenerate output")
        clean = (self.proj / "app.py").read_text()
        self.assertIn("format_time", clean,
                      "residue must be gone — the committed base wins")

    def test_discard_keeps_ignored_evidence_and_kb(self):
        self.residue()
        (self.proj / ".gitignore").write_text(
            "*_output.txt\nregression_*.log\nregression_repair_*.txt\n")
        evidence = self.proj / "issue_3_output.txt"
        evidence.write_text("degenerate stdout")
        kb = self.proj / "kb" / "graph.json"
        kb.parent.mkdir()
        kb.write_text('{"nodes": [], "edges": []}')
        phases._discard_residue(self.proj, 3, "degenerate output")
        self.assertTrue(evidence.exists(),
                        "ignored run evidence is not product — it survives")
        self.assertTrue(kb.exists(),
                        "the KB is the run's bookkeeping — it survives")

    def test_discard_removes_untracked_product_residue(self):
        # an untracked source file the worker added mid-issue is residue
        # too — it must not sit in the tree pretending to be the base
        self.residue()
        (self.proj / "half_done_feature.py").write_text("x = 1\n")
        phases._discard_residue(self.proj, 3, "degenerate output")
        self.assertFalse((self.proj / "half_done_feature.py").exists())

    def test_discard_is_a_noop_on_a_clean_tree(self):
        # a blocked issue that wrote nothing must not touch the tree
        before = (self.proj / "app.py").read_text()
        phases._discard_residue(self.proj, 3, "degenerate output")
        self.assertEqual((self.proj / "app.py").read_text(), before)

    def test_tree_is_clean_ignores_untracked_evidence(self):
        (self.proj / "issue_3_output.txt").write_text("evidence")
        (self.proj / "regression_3.log").write_text("log")
        self.assertTrue(phases._tree_is_clean(self.proj))
        self.residue()
        self.assertFalse(phases._tree_is_clean(self.proj))


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
