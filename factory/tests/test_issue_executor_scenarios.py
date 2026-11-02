import json
import tempfile
import unittest
from pathlib import Path

from pipeline import phases, skill_scenarios


FACTORY_SKILLS = Path(__file__).resolve().parents[1] / "skills"
SCENARIOS = FACTORY_SKILLS / "issue-executor/test_scenarios.yaml"


class IssueExecutorScenarios(unittest.TestCase):
    def test_protocol_scenarios_cover_implementation_and_handoffs(self):
        report = skill_scenarios.evaluate_suite(SCENARIOS, skills_root=FACTORY_SKILLS)
        self.assertEqual(report["format"]["status"], "passed",
                         report["format"]["errors"])
        self.assertEqual(report["simulated"]["status"], "passed")
        self.assertEqual(
            [row["id"] for row in report["simulated"]["scenarios"]],
            ["implementation-with-test-evidence", "consult-on-missing-fact",
             "request-approval-with-scope-context", "implement-after-consultation",
             "consultation-still-unresolved"])

    def test_claimed_tool_actions_without_execution_records_are_rejected(self):
        report = skill_scenarios.simulate({
            "scenarios": [{
                "id": "narrated-only",
                "inputs": {
                    "simulated_response": (
                        "I wrote answer.py and ran pytest; all tests passed."),
                    "execution_log": [],
                },
                "assertions": [{"type": "tool_claim_has_execution_evidence"}],
            }],
        })
        self.assertEqual(report["status"], "failed")
        self.assertIn("no execution log",
                      report["scenarios"][0]["assertions"][0]["detail"])

    def test_temporary_project_regression_evidence_comes_from_pytest(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "answer.py").write_text("def answer(): return 0\n")
            (project / "tests").mkdir()
            test_file = project / "tests/test_answer.py"
            test_file.write_text(
                "from answer import answer\n"
                "def test_answer(): assert answer() == 42\n")
            spec = project / "spec.md"
            plan = project / "issues.md"
            spec.write_text("# Spec\nR1: answer() returns 42.\n")
            plan.write_text(
                "## Issue #1: Implement answer\nReturn 42.\n"
                "Test strategy: Assert answer() returns 42.\nDependencies: none.\n")
            original_documents = (spec.read_bytes(), plan.read_bytes())

            self.assertEqual(phases.run_regression(project, 1), "failed")
            test_record = json.loads((project / ".siesta/tests.json").read_text())
            self.assertEqual(test_record["status"], "failed")

            (project / "answer.py").write_text("def answer(): return 42\n")
            self.assertEqual(phases.run_regression(project, 1), "passed")
            test_record = json.loads((project / ".siesta/tests.json").read_text())
            self.assertEqual(test_record["status"], "passed")
            self.assertEqual(test_record["passed"], ["tests/test_answer.py::test_answer"])
            self.assertEqual((spec.read_bytes(), plan.read_bytes()), original_documents)


if __name__ == "__main__":
    unittest.main()
