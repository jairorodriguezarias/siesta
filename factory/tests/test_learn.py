import json
import tempfile
import unittest
from pathlib import Path

from pipeline import learn, skill_versions
from pipeline.kb import Graph

LEARNER_OUTPUT = """\
ISSUE_LEARNING #2:
  Stuck: true
  Root cause:
    - missing edge-case guidance

  Actions:
    LEARNING: Always seed the DB — avoids flaky first-run tests.
    SKILL_IMPROVEMENT: issue-executor — add Red Flag for skipping regressions
    NEW_SKILL: smoke-test-runner — covers local server checks
SKILL_UPDATE_START: issue-executor
---
name: issue-executor
new: yes
---

## Red Flags (new)

- Skipping the regression suite before starting a new issue.
SKILL_UPDATE_END
"""

EMPTY_OUTPUT = "NO_ACTION: nothing to learn (rare)"

BLANK_BLOCK = """\
SKILL_UPDATE_START: issue-executor

SKILL_UPDATE_END
"""

FRAGMENT_BLOCK = """\
SKILL_UPDATE_START: issue-executor
## Red Flags (new)

- a section fragment, no frontmatter
SKILL_UPDATE_END
"""

DOT_NAME_BLOCK = """\
SKILL_UPDATE_START: ..
---
name: whatever
body long enough to pass the substance check if the name were allowed
SKILL_UPDATE_END
"""


class IssueFacts(unittest.TestCase):
    """The per-issue learner must read THIS issue's facts, not a substring
    neighbor's: "Issue #1" also matches inside "Issue #10 blocked" — the
    blocker flag would fire for a completed issue #1 and log false facts
    into the global KB (the factory's long-term memory)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        self.kb = Graph(self.proj / "kb" / "graph.json")

    def facts(self, n: int) -> dict:
        return learn._issue_facts(self.proj, n, "write hello", self.kb)

    def test_issue_1_not_flagged_blocked_by_issue_10_blocker(self):
        self.kb.node("blocker", "Issue #10 blocked after diagnosis", "boom")
        self.assertFalse(self.facts(1)["flags"]["blocker"])

    def test_own_issue_blocker_still_flags(self):
        self.kb.node("blocker", "Issue #1 blocked after diagnosis", "boom")
        self.assertTrue(self.facts(1)["flags"]["blocker"])

    def test_own_issue_blocker_flagged_after_higher_numbered_blocker(self):
        # the KB insertion order must not matter — only the number
        self.kb.node("blocker", "Issue #10 blocked after diagnosis", "boom")
        self.kb.node("blocker", "Issue #1 degenerate output", "boom")
        self.assertTrue(self.facts(1)["flags"]["blocker"])

    def test_clean_project_flags_nothing(self):
        self.assertEqual(self.facts(1)["flags"],
                         {"consult": False, "proxy": False,
                          "retry": False, "blocker": False})


class ActOnLearnings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gkb = Graph(Path(self.tmp.name) / "global.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_learning_lines_become_global_kb_nodes(self):
        counts = learn.act_on_learnings(LEARNER_OUTPUT, self.gkb, 3)
        learnings = [n["summary"] for n in self.gkb.query("learning")]
        self.assertEqual(learnings, ["Always seed the DB"])
        self.assertEqual(counts["learnings"], 1)
        self.assertEqual(counts["improvements"], 1)
        self.assertEqual(counts["new_skills"], 1)

    def test_skill_actions_use_observation_nodes_with_issue_ref(self):
        learn.act_on_learnings(LEARNER_OUTPUT, self.gkb, 3)
        observations = [n["summary"] for n in self.gkb.query("skill_observation")]
        self.assertIn("SKILL_IMPROVEMENT: issue-executor (issue #3)", observations)
        self.assertIn("NEW_SKILL: smoke-test-runner (issue #3)", observations)

    def test_no_action_yields_zeroes(self):
        counts = learn.act_on_learnings(EMPTY_OUTPUT, self.gkb, 1)
        self.assertEqual(counts, {"learnings": 0, "improvements": 0, "new_skills": 0})

    def test_project_level_actions_do_not_log_issue_none(self):
        # round-5: project-level learning calls with n=None — the KB summary
        # must say "project level", not "(issue #None)"
        learn.act_on_learnings(LEARNER_OUTPUT, self.gkb, None)
        observations = [n["summary"] for n in self.gkb.query("skill_observation")]
        self.assertIn("SKILL_IMPROVEMENT: issue-executor (project level)", observations)
        self.assertNotIn("SKILL_IMPROVEMENT: issue-executor (issue #None)", observations)


class SkillProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skills = Path(self.tmp.name) / "skills"
        self.skills.mkdir()
        self.project = Path(self.tmp.name) / "project"

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_update_records_previous_candidate_reason_and_evidence_without_activation(self):
        target = self.skills / "issue-executor" / "SKILL.md"
        target.parent.mkdir()
        previous = "---\nname: issue-executor\ndescription: Existing skill.\n---\nold body\n"
        target.write_text(previous)
        graph = Graph(Path(self.tmp.name) / "global.json")
        ids = learn.propose_skill_updates(
            LEARNER_OUTPUT, self.skills, graph, project=self.project, issue=2,
            evidence={"test": "issue_2_output.txt"})
        self.assertEqual(len(ids), 1)
        record = json.loads(graph.get(ids[0])["detail"])
        self.assertEqual(record["previous_content"], previous)
        self.assertIn("new: yes", record["proposed_content"])
        self.assertEqual(record["reason"], "add Red Flag for skipping regressions")
        self.assertEqual(record["evidence"]["sources"], {"test": "issue_2_output.txt"})
        self.assertEqual(record["status"], "pending")
        self.assertEqual(target.read_text(), previous)

    def test_new_factory_skill_requires_new_skill_action_and_stays_pending(self):
        output = """NEW_SKILL: scenario-author — support repeatable validation cases
SKILL_UPDATE_START: scenario-author
---
name: scenario-author
description: Write validation scenarios.
---
Use concise repeatable cases with verifiable evidence.
SKILL_UPDATE_END
"""
        graph = Graph(Path(self.tmp.name) / "global.json")
        ids = learn.propose_skill_updates(output, self.skills, graph,
                                         project=self.project, issue=None)
        self.assertEqual(len(ids), 1)
        self.assertEqual(json.loads(graph.get(ids[0])["detail"])["previous_content"], "")
        self.assertFalse((self.skills / "scenario-author/SKILL.md").exists())

    def test_previous_content_and_skill_scope_come_from_run_pin(self):
        target = self.skills / "issue-executor/SKILL.md"
        target.parent.mkdir()
        previous = "---\nname: issue-executor\ndescription: Pinned.\n---\nKeep this rule.\n"
        target.write_text(previous)
        graph = Graph(Path(self.tmp.name) / "global.json")
        roots = skill_versions.source_roots()
        roots["factory"] = self.skills
        skill_versions.pin_project(self.project, roots=roots)
        target.unlink()
        output = """SKILL_IMPROVEMENT: issue-executor — preserve the existing constraint
SKILL_UPDATE_START: issue-executor
---
name: issue-executor
description: Improved.
---
Keep this rule and add a regression check that proves it remains enforced.
SKILL_UPDATE_END
"""
        learn.act_on_learnings(output, graph, 4, skills_dir=self.skills,
                               project=self.project)
        ids = learn.propose_skill_updates(output, self.skills, graph,
                                          project=self.project, issue=4)
        self.assertEqual(len(ids), 1)
        record = json.loads(graph.get(ids[0])["detail"])
        self.assertEqual(record["previous_content"], previous)
        self.assertFalse(target.exists())

    def test_adapted_skill_is_not_an_authorized_factory_proposal(self):
        output = """SKILL_IMPROVEMENT: interview-me — add more detail
SKILL_UPDATE_START: interview-me
---
name: interview-me
description: Updated interview.
---
This replacement is intentionally outside factory skills.
SKILL_UPDATE_END
"""
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(output, self.skills, graph,
                                                    project=self.project, issue=1), [])
        self.assertEqual(graph.query("skill_proposal"), [])
        learn.act_on_learnings(output, graph, 1, skills_dir=self.skills)
        self.assertEqual(graph.query("skill_observation"), [])

    def test_new_skill_cannot_shadow_an_adapted_skill(self):
        adapted = Path(__file__).resolve().parents[2] / ".agents/skills/interview-me"
        if not (adapted / "SKILL.md").is_file():
            self.skipTest("adapted interview skill is not installed in this checkout")
        output = """NEW_SKILL: interview-me — duplicate an adapted workflow
SKILL_UPDATE_START: interview-me
---
name: interview-me
description: A duplicate.
---
Do the same work as the adapted skill.
SKILL_UPDATE_END
"""
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(output, self.skills, graph,
                                                    project=self.project, issue=1), [])
        self.assertEqual(graph.query("skill_proposal"), [])

    def test_path_traversal_is_rejected_without_writing_outside_factory(self):
        output = """NEW_SKILL: ../escape — malicious destination
SKILL_UPDATE_START: ../escape
---
name: escape
description: Invalid destination.
---
This must not be written outside the factory skill directory.
SKILL_UPDATE_END
"""
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(output, self.skills, graph,
                                                    project=self.project, issue=1), [])
        self.assertFalse((self.skills.parent / "escape").exists())

    def test_malformed_candidate_is_not_recorded(self):
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(FRAGMENT_BLOCK, self.skills, graph,
                                                    project=self.project, issue=1), [])
        self.assertEqual(graph.query("skill_proposal"), [])

    def test_blank_block_rejected_existing_skill_kept(self):
        target = self.skills / "issue-executor" / "SKILL.md"
        target.parent.mkdir()
        target.write_text("---\nname: issue-executor\n---\nold body")
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(
            BLANK_BLOCK, self.skills, graph, project=self.project, issue=1), [])
        self.assertIn("old body", target.read_text())

    def test_fragment_without_frontmatter_rejected(self):
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(
            FRAGMENT_BLOCK, self.skills, graph, project=self.project, issue=1), [])
        self.assertFalse((self.skills / "issue-executor").exists())

    def test_dot_name_rejected_nothing_written_outside(self):
        graph = Graph(Path(self.tmp.name) / "global.json")
        self.assertEqual(learn.propose_skill_updates(
            DOT_NAME_BLOCK, self.skills, graph, project=self.project, issue=1), [])
        self.assertEqual(list(self.skills.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
