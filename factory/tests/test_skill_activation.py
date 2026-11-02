"""Factory skill activation requires independent and executable evidence."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import skill_activation, skill_versions
from pipeline.kb import Graph


PASS = json.dumps({"version": 1, "verdict": "pass", "summary": "Supported change",
                   "findings": []})
FINDINGS = json.dumps({"version": 1, "verdict": "findings",
                       "summary": "Weakens the test gate", "findings": [{
                           "id": "F1", "severity": "major", "target": "verification",
                           "evidence": "Candidate asks to skip tests",
                           "requested_fix": "Restore the test gate"}]})


class SkillActivationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skills = self.root / "skills"
        self.active = self.skills / "demo" / "SKILL.md"
        self.active.parent.mkdir(parents=True)
        self.previous = "---\nname: demo\n---\nKeep tests and record their real results.\n"
        self.candidate = self.previous + "Use clearer failure evidence.\n"
        self.active.write_text(self.previous)
        (self.active.parent / "test_scenarios.yaml").write_text("suite exists\n")
        self.project = self.root / "project"
        self.project.mkdir()
        self.graph = Graph(self.root / "graph.json")
        self.proposal = self.graph.node("skill_proposal", "demo", json.dumps({
            "skill": "demo", "scope": "factory", "previous_content": self.previous,
            "proposed_content": self.candidate, "reason": "Issue evidence revealed unclear failures",
            "evidence": {"test": "test_failure"}, "status": "pending"}))

    def _evaluate(self, suite, root):
        self.assertEqual((root / "demo" / "SKILL.md").read_text(), self.candidate)
        self.assertEqual(suite.name, "test_scenarios.yaml")
        return {stage: {"status": "passed", "scenarios": []}
                for stage in ("format", "simulated", "real")}

    def _run(self, reviewer=lambda *_: PASS, evaluator=None):
        return skill_activation.review_and_activate(
            [self.proposal], self.graph, project=self.project,
            skills_dir=self.skills, reviewer=reviewer,
            evaluator=evaluator or self._evaluate)

    def _payload(self):
        return json.loads(self.graph.get(self.proposal)["detail"])

    def test_accepted_candidate_keeps_prior_version_and_current_project_pin(self):
        pinned = skill_versions.pin_project(
            self.project, roots={"factory": self.skills, "adapted": self.root / "adapted"})
        self.assertEqual(len(pinned["skills"]), 1)
        self.assertEqual(self._run()[self.proposal], "active")
        self.assertEqual(self.active.read_text(), self.candidate)
        self.assertEqual(skill_versions.pinned_skill(
            self.project, "demo", roots={"factory": self.skills,
                                          "adapted": self.root / "adapted"}), self.previous)
        history = self.skills.parent / ".runtime" / "skill-history" / "demo"
        self.assertEqual(len(list(history.glob("*.md"))), 1)
        self.assertEqual(self._payload()["status"], "active")

    def test_review_rejection_does_not_activate(self):
        result = self._run(reviewer=lambda *_: FINDINGS)
        self.assertEqual(result[self.proposal], "rejected")
        self.assertEqual(self.active.read_text(), self.previous)
        self.assertEqual(self._payload()["validation"]["review"][-1]["findings"][0]["id"], "F1")

    def test_failed_real_evaluation_remains_pending(self):
        def failing(_suite, _root):
            report = self._evaluate(_suite, _root)
            report["real"]["status"] = "failed"
            return report
        self.assertEqual(self._run(evaluator=failing)[self.proposal], "pending")
        self.assertEqual(self.active.read_text(), self.previous)

    def test_changed_active_version_is_conflict(self):
        self.active.write_text(self.previous + "Other edit.\n")
        self.assertEqual(self._run()[self.proposal], "conflict")
        self.assertEqual(self._payload()["status"], "pending")

    def test_invalid_reviewer_gets_one_retry_then_stays_pending(self):
        calls = []
        def invalid(*_args):
            calls.append(1)
            return "APPROVED"
        self.assertEqual(self._run(reviewer=invalid)[self.proposal], "pending")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.active.read_text(), self.previous)

    def test_interrupted_swap_restores_previous_content(self):
        history = self.skills.parent / ".runtime" / "skill-history" / "demo"
        history.mkdir(parents=True)
        skill_activation._save_json(history / "journal.json", {
            "skill": "demo", "proposal_id": self.proposal,
            "previous_exists": True, "previous_content": self.previous,
            "candidate_sha256": skill_activation._digest(self.candidate)})
        self.active.write_text(self.candidate)
        with skill_activation._activation_lock(self.skills) as state:
            skill_activation._recover(self.skills, state, self.graph)
        self.assertEqual(self.active.read_text(), self.previous)
        self.assertFalse((history / "journal.json").exists())
        self._run()
        self.assertEqual(self.active.read_text(), self.candidate)
        self.assertFalse((history / "journal.json").exists())
        self.assertEqual(self._payload()["status"], "active")


if __name__ == "__main__":
    unittest.main()
