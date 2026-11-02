import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import evaluate, skill_scenarios


VALID = """version: 1
skill: executor
agent: consultant
scenarios:
  - id: concise-answer
    inputs:
      prompt: Answer with a short greeting.
      simulated_response: Hello there.
      execution_log: []
    assertions:
      - type: contains
        value: Hello
      - type: not_contains
        value: traceback
"""


def scenario_file(root: Path, content: str = VALID) -> Path:
    path = root / "executor" / "test_scenarios.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class SkillScenarioValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "skills"
        self.root.mkdir()
        skill = self.root / "executor"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: executor\ndescription: Test executor.\n---\nUse evidence.\n")

    def test_valid_scenario_has_separate_format_simulation_and_real_results(self):
        path = scenario_file(self.root)
        report = skill_scenarios.evaluate_suite(path, skills_root=self.root)
        self.assertEqual(report["format"]["status"], "passed")
        self.assertEqual(report["simulated"]["status"], "passed")
        self.assertEqual(report["real"]["status"], "not_run")
        self.assertEqual(report["simulated"]["scenarios"][0]["id"], "concise-answer")

    def test_invalid_yaml_is_a_format_failure_and_skips_later_stages(self):
        path = scenario_file(self.root, "version: [\nnot: yaml\n")
        report = skill_scenarios.evaluate_suite(
            path, real=True, output_dir=Path(self.tmp.name) / "run",
            skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")
        self.assertEqual(report["simulated"]["status"], "skipped")
        self.assertEqual(report["real"]["status"], "skipped")

    def test_unknown_assertion_is_rejected_during_format_validation(self):
        content = VALID.replace("type: contains", "type: model_says_ok")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")
        self.assertIn("unsupported assertion", " ".join(report["format"]["errors"]))

    def test_marker_assertion_ignores_fenced_examples(self):
        content = VALID.replace(
            "simulated_response: Hello there.",
            'simulated_response: "```text\\nAPPROVED\\n```"')
        content = content.replace(
            "      - type: contains\n        value: Hello",
            "      - type: marker_outside_fences\n"
            "        marker: APPROVED\n        expected: false")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "passed")
        self.assertEqual(report["simulated"]["status"], "passed")

    def test_unknown_fields_and_duplicate_yaml_keys_are_rejected(self):
        unknown = VALID.replace("agent: consultant", "agent: consultant\nextra: true")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, unknown), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")
        duplicate = VALID.replace("version: 1", "version: 1\nversion: 1")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, duplicate), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")
        non_string_key = VALID.replace("      prompt:", "      1:")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, non_string_key), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")

    def test_response_claiming_tool_execution_fails_without_an_execution_log(self):
        content = VALID.replace(
            "simulated_response: Hello there.",
            "simulated_response: I ran the tests and all passed.")
        content = content.replace(
            "      - type: contains\n        value: Hello",
            "      - type: tool_claim_has_execution_evidence")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), skills_root=self.root)
        self.assertEqual(report["format"]["status"], "passed")
        self.assertEqual(report["simulated"]["status"], "failed")
        self.assertIn("execution log", report["simulated"]["scenarios"][0]
                      ["assertions"][0]["detail"])

    def test_response_claim_with_structured_execution_log_passes(self):
        content = VALID.replace(
            "      execution_log: []",
            "      execution_log:\n"
            "        - tool: bash\n"
            "          action: run unit tests\n"
            "          result: exit code 0")
        content = content.replace(
            "simulated_response: Hello there.",
            "simulated_response: I ran the tests and all passed.")
        content = content.replace(
            "      - type: contains\n        value: Hello",
            "      - type: tool_claim_has_execution_evidence")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), skills_root=self.root)
        self.assertEqual(report["simulated"]["status"], "passed")

    def test_real_evaluation_does_not_reuse_simulated_execution_records(self):
        content = VALID.replace(
            "      execution_log: []",
            "      execution_log:\n"
            "        - tool: bash\n"
            "          action: run unit tests\n"
            "          result: exit code 0")
        content = content.replace(
            "simulated_response: Hello there.",
            "simulated_response: I ran the tests and all passed.")
        content = content.replace(
            "      - type: contains\n        value: Hello",
            "      - type: tool_claim_has_execution_evidence")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), real=True,
            output_dir=Path(self.tmp.name) / "run",
            skills_root=self.root,
            invoker=lambda **_: ("I ran the tests and all passed.", []))
        self.assertEqual(report["simulated"]["status"], "passed")
        self.assertEqual(report["real"]["status"], "failed")

    def test_real_result_passes_with_runtime_execution_records(self):
        content = VALID.replace(
            "      - type: contains\n        value: Hello",
            "      - type: tool_claim_has_execution_evidence")
        content = content.replace(
            "simulated_response: Hello there.",
            "simulated_response: I ran the tests and all passed.")
        report = skill_scenarios.evaluate_suite(
            scenario_file(self.root, content), real=True,
            output_dir=Path(self.tmp.name) / "run",
            skills_root=self.root,
            invoker=lambda **_: ("I ran the tests and all passed.", [
                {"tool": "bash", "action": "run tests", "result": "exit code 0"}]))
        self.assertEqual(report["real"]["status"], "passed")

    def test_suite_path_must_belong_to_factory_skill_root(self):
        external = Path(self.tmp.name) / "other" / "test_scenarios.yaml"
        external.parent.mkdir()
        external.write_text(VALID)
        report = skill_scenarios.evaluate_suite(external, skills_root=self.root)
        self.assertEqual(report["format"]["status"], "failed")

    def test_existing_evaluation_cli_writes_a_separate_skill_report(self):
        factory = Path(self.tmp.name) / "factory"
        skills = factory / "skills"
        skill = skills / "executor"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: executor\ndescription: Test executor.\n---\nUse evidence.\n")
        suite = scenario_file(skills)
        output = Path(self.tmp.name) / "evaluation"
        with patch.object(evaluate, "FACTORY", factory):
            with self.assertRaises(SystemExit) as raised:
                evaluate.main(["--output", str(output), "--skill-scenarios", str(suite)])
        self.assertEqual(raised.exception.code, 0)
        report = json.loads((output / "results.json").read_text())
        self.assertEqual(report["skill_scenarios"]["format"]["status"], "passed")
        self.assertEqual(report["skill_scenarios"]["simulated"]["status"], "passed")
        self.assertEqual(report["skill_scenarios"]["real"]["status"], "not_run")

    def test_human_proxy_scenarios_cover_decisions_and_supply_full_context(self):
        factory_skills = Path(__file__).resolve().parents[1] / "skills"
        path = factory_skills / "human-proxy/test_scenarios.yaml"
        report = skill_scenarios.evaluate_suite(path, skills_root=factory_skills)
        self.assertEqual(report["format"]["status"], "passed",
                         report["format"]["errors"])
        self.assertEqual(report["simulated"]["status"], "passed")
        suite = skill_scenarios.load_suite(path, skills_root=factory_skills)
        self.assertEqual([row["id"] for row in suite["scenarios"]],
                         ["approve-local-export", "reject-cloud-sync",
                          "request-missing-destination", "fenced-example-is-not-approval"])
        context = suite["scenarios"][0]["inputs"]["prompt"]
        for evidence in ("Original intent", "Decision D-1", "Decision D-2",
                         "Current specification", "Relevant context"):
            self.assertIn(evidence, context)


if __name__ == "__main__":
    unittest.main()
