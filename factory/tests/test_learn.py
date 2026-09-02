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