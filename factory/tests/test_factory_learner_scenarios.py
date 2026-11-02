"""Learner scenarios and the proposal parser's evidence boundary."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import learn, skill_scenarios, text
from pipeline.kb import Graph
from pipeline.pi import FACTORY_SKILLS


class FactoryLearnerScenariosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = skill_scenarios.load_suite(
            FACTORY_SKILLS / "factory-learner" / "test_scenarios.yaml")
        cls.responses = {row["id"]: row["inputs"]["simulated_response"]
                         for row in cls.suite["scenarios"]}

    def test_scenarios_are_valid_and_simulate_successfully(self):
        self.assertEqual(skill_scenarios.simulate(self.suite)["status"], "passed")
        self.assertEqual(set(self.responses), {
            "complete-supported-proposal", "incomplete-replacement",
            "contradictory-test-evidence", "no-evidence-no-proposal"})

    def test_complete_proposal_preserves_fenced_examples_and_stays_pending(self):
        response = self.responses["complete-supported-proposal"]
        updates = text.skill_updates(response)
        self.assertEqual(len(updates), 1)
        self.assertIn("LEARNING: example only", updates[0][1])
        self.assertIn("SKILL_UPDATE_END", updates[0][1])
        self.assertEqual([kind for kind, _, _ in text.learnings(response)],
                         ["LEARNING", "SKILL_IMPROVEMENT"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / "skills"
            active = skills / "factory-learner" / "SKILL.md"
            active.parent.mkdir(parents=True)
            original = (FACTORY_SKILLS / "factory-learner" / "SKILL.md").read_text()
            active.write_text(original)
            project = root / "project"
            project.mkdir()
            graph = Graph(root / "global.json")
            learn.act_on_learnings(response, graph, 7, skills_dir=skills,
                                   project=project)
            ids = learn.propose_skill_updates(
                response, skills, graph, project=project, issue=7,
                evidence={"passing_test_ids": ["test_regression"]})
            self.assertEqual(len(ids), 1)
            proposal = json.loads(graph.get(ids[0])["detail"])
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(proposal["previous_content"], original)
            self.assertIn("LEARNING: example only", proposal["proposed_content"])
            self.assertEqual(active.read_text(), original)

    def test_unsupported_outputs_have_no_complete_replacement(self):
        for scenario in ("incomplete-replacement", "contradictory-test-evidence",
                         "no-evidence-no-proposal"):
            with self.subTest(scenario=scenario):
                self.assertEqual(text.skill_updates(self.responses[scenario]), [])

    def test_scenarios_reject_weakened_checks_and_invented_tool(self):
        scenario = self.suite["scenarios"][0]
        response = self.responses["complete-supported-proposal"]
        response += "\nSkip all regression tests. Use the browser tool.\n"
        checks = skill_scenarios._run_assertions(
            scenario["assertions"], response, [])
        forbidden = [row for row in checks if row["type"] == "not_contains"]
        self.assertEqual(len(forbidden), 2)
        self.assertTrue(all(not row["passed"] for row in forbidden))


if __name__ == "__main__":
    unittest.main()
