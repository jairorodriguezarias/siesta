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

    def test_phase1_intent_lives_in_body_user_is_output_directive(self):
        captured = {}

        def fake(role, body, user, **kw):
            captured.update(role=role, body=body, user=user)
            return "# Spec\n\nA tiny caesar cipher CLI spec.\n"

        with patch.object(phases, "run_pi", fake):
            phases.phase1(self.proj, "caesar", "a tiny caesar cipher cli",
                          "n1", self.kb)
        self.assertIn("a tiny caesar cipher cli", captured["body"])
        self.assertIn("spec.md", captured["user"])
        self.assertNotIn("caesar", captured["user"])

    def test_phase2_spec_lives_in_body_user_is_output_directive(self):
        captured = {}

        def fake(role, body, user, **kw):
            captured.update(body=body, user=user)
            return "## Issue #1: Add encode\n\nImplement shift encoding.\n"

        with patch.object(phases, "run_pi", fake):
            phases.phase2(self.proj, "caesar", "n1", self.kb)
        self.assertIn("caesar cipher CLI", captured["body"])
        self.assertIn("issues.md", captured["user"])
        self.assertNotIn("caesar cipher CLI", captured["user"])

    def test_phase2_issues_saved_from_model_text(self):
        out = "## Issue #1: Add encode\n\nImplement shift encoding.\n"
        with patch.object(phases, "run_pi", lambda *a, **k: out):
            n = phases.phase2(self.proj, "caesar", "n1", self.kb)
        self.assertEqual(n, 1)
        self.assertTrue((self.proj / "issues.md").read_text().startswith("## Issue #1"))


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


if __name__ == "__main__":
    unittest.main()