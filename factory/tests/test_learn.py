import json
import tempfile
import unittest
from pathlib import Path

from pipeline import learn
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

    def test_skill_actions_use_decision_nodes_with_issue_ref(self):
        learn.act_on_learnings(LEARNER_OUTPUT, self.gkb, 3)
        decisions = [n["summary"] for n in self.gkb.query("decision")]
        self.assertIn("Skill improvement: issue-executor (issue #3)", decisions)
        self.assertIn("New skill proposed: smoke-test-runner (issue #3)", decisions)

    def test_no_action_yields_zeroes(self):
        counts = learn.act_on_learnings(EMPTY_OUTPUT, self.gkb, 1)
        self.assertEqual(counts, {"learnings": 0, "improvements": 0, "new_skills": 0})

    def test_project_level_actions_do_not_log_issue_none(self):
        # round-5: project-level learning calls with n=None — the KB summary
        # must say "project level", not "(issue #None)"
        learn.act_on_learnings(LEARNER_OUTPUT, self.gkb, None)
        decisions = [n["summary"] for n in self.gkb.query("decision")]
        self.assertIn("Skill improvement: issue-executor (project level)", decisions)
        self.assertNotIn("Skill improvement: issue-executor (issue #None)", decisions)


class ApplySkillUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skills = Path(self.tmp.name) / "skills"
        self.skills.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_updates_existing_skill_file(self):
        target = self.skills / "issue-executor" / "SKILL.md"
        target.parent.mkdir()
        target.write_text("---\nname: issue-executor\n---\nold body")
        applied = learn.apply_skill_updates(LEARNER_OUTPUT, self.skills)
        self.assertEqual(applied, ["issue-executor"])
        self.assertIn("new: yes", target.read_text())
        self.assertNotIn("old body", target.read_text())

    def test_creates_new_skill_dir_when_missing(self):
        applied = learn.apply_skill_updates(LEARNER_OUTPUT, self.skills)
        self.assertEqual(applied, ["issue-executor"])
        self.assertTrue((self.skills / "issue-executor" / "SKILL.md").exists())

    def test_no_updates_means_nothing_applied(self):
        self.assertEqual(learn.apply_skill_updates(EMPTY_OUTPUT, self.skills), [])

    def test_blank_block_rejected_existing_skill_kept(self):
        # #20: an empty block must not wipe an existing SKILL.md
        target = self.skills / "issue-executor" / "SKILL.md"
        target.parent.mkdir()
        target.write_text("---\nname: issue-executor\n---\nold body")
        self.assertEqual(learn.apply_skill_updates(BLANK_BLOCK, self.skills), [])
        self.assertIn("old body", target.read_text())

    def test_fragment_without_frontmatter_rejected(self):
        # #20: a section fragment would replace the whole file — reject it
        self.assertEqual(learn.apply_skill_updates(FRAGMENT_BLOCK, self.skills), [])
        self.assertFalse((self.skills / "issue-executor").exists())

    def test_dot_name_rejected_nothing_written_outside(self):
        self.assertEqual(learn.apply_skill_updates(DOT_NAME_BLOCK, self.skills), [])
        self.assertEqual(list(self.skills.rglob("SKILL.md")), [])


if __name__ == "__main__":
    unittest.main()