import unittest

from pipeline import text


ISSUES_MD = """\
Some preamble text.

## Issue #1: Review and verify existing code

Review all code files in the project.

**Acceptance criteria:**
- All HTML is valid
- Model names match factory/config/models.json

## Issue #2: Add tests

Add a test suite with pytest.
"""

MARKER_OUTPUT = """\
Rule from the prompt, indented two spaces:
  CONSULT: <question>
  PROXY_REQUEST: <what needs approval>
Real marker follows
CONSULT: tests fail with KeyError
CONTEXT: tried printing the variable
CODE: KeyError: 'name'
"""

LEARNINGS_OUTPUT = """\
LEARNING: Prefer stdlib only — keeps installs local — even for parsing needs.
SKILL_IMPROVEMENT: Add Red Flag "skip the test" — When time pressure tempts you, refuse.
NEW_SKILL: api-and-interface-design — Design CLIs as small modules with pure functions.
"""

SKILL_UPDATE_OUTPUT = """\
intro text
SKILL_UPDATE_START: issue-executor

## Red Flags (new)

- Skip the regression suite.
SKILL_UPDATE_END
trailing text
SKILL_UPDATE_START: new-skill
body two
SKILL_UPDATE_END
"""


class SplitIssues(unittest.TestCase):
    def test_extracts_numbered_sections_in_order(self):
        issues = text.split_issues(ISSUES_MD)
        self.assertEqual([n for n, _ in issues], [1, 2])

    def test_body_runs_until_next_header(self):
        body1 = dict(text.split_issues(ISSUES_MD))[1]
        self.assertIn("Review all code files", body1)
        self.assertIn("All HTML is valid", body1)
        self.assertNotIn("Add a test suite", body1)

    def test_no_headers_yields_nothing(self):
        self.assertEqual(text.split_issues("just text, no issues"), [])


class AnchoredMarkers(unittest.TestCase):
    def test_marker_at_line_start_matches(self):
        self.assertIsNotNone(text.CONSULT.search(MARKER_OUTPUT))
        self.assertIsNotNone(text.PROXY.search("line before\nPROXY_REQUEST: approve me"))
        self.assertIsNotNone(text.SKIP.search("SKIP: log blocker and continue\nnext"))

    def test_indented_rule_examples_do_not_match(self):
        # The worker prompt's own protocol examples are indented two
        # spaces; they must not be read as real model output.
        indented_only = "Rules:\n  CONSULT: <question>\n  PROXY_REQUEST: <what needs approval>"
        self.assertIsNone(text.CONSULT.search(indented_only))
        self.assertIsNone(text.PROXY.search(indented_only))

    def test_substring_inside_a_line_does_not_match(self):
        self.assertIsNone(text.REJECTED.search("the request was NOT_REJECTED today"))


class LearningLines(unittest.TestCase):
    def test_splits_at_first_em_dash(self):
        kind, summary, detail = text.learnings(LEARNINGS_OUTPUT)[0]
        self.assertEqual(kind, "LEARNING")
        self.assertEqual(summary, "Prefer stdlib only")
        self.assertEqual(detail, "keeps installs local — even for parsing needs.")

    def test_three_kinds_recognized(self):
        kinds = [kind for kind, _, _ in text.learnings(LEARNINGS_OUTPUT)]
        self.assertEqual(kinds, ["LEARNING", "SKILL_IMPROVEMENT", "NEW_SKILL"])

    def test_lines_without_marker_ignored(self):
        self.assertEqual(text.learnings("random line\ndefinitely not"), [])

    def test_accepts_plain_hyphen_as_separator(self):
        # #14: models emit "-" or "–" as often as the em dash the prompt shows
        kind, summary, detail = text.learnings(
            "SKILL_IMPROVEMENT: add Red Flag - refuse to skip tests")[0]
        self.assertEqual(kind, "SKILL_IMPROVEMENT")
        self.assertEqual(summary, "add Red Flag")
        self.assertEqual(detail, "refuse to skip tests")

    def test_accepts_en_dash_as_separator(self):
        kind, summary, detail = text.learnings(
            "LEARNING: seed the DB – avoids flaky first-run tests.")[0]
        self.assertEqual(summary, "seed the DB")
        self.assertEqual(detail, "avoids flaky first-run tests.")

    def test_summary_only_line_gets_empty_detail(self):
        # #14: the detail was mandatory, so summary-only lines were dropped
        kind, summary, detail = text.learnings("LEARNING: tests first, always")[0]
        self.assertEqual(summary, "tests first, always")
        self.assertEqual(detail, "")

    def test_hyphenated_word_is_not_a_separator(self):
        # "-v" is glued to the next word: no space after the dash
        kind, summary, _ = text.learnings(
            "LEARNING: support the -v flag everywhere")[0]
        self.assertEqual(summary, "support the -v flag everywhere")


class SkillUpdateBlocks(unittest.TestCase):
    def test_extracts_named_blocks(self):
        updates = text.skill_updates(SKILL_UPDATE_OUTPUT)
        self.assertEqual([name for name, _ in updates], ["issue-executor", "new-skill"])
        self.assertIn("Skip the regression suite.", updates[0][1])
        self.assertEqual(updates[1][1].strip(), "body two")
        self.assertNotIn("intro text", updates[0][1])


class Helpers(unittest.TestCase):
    def test_after_matches_grep_dash_a_semantics(self):
        # like `grep -A 1`: the marker line plus one following line
        m = text.CONSULT.search(MARKER_OUTPUT)
        grabbed = text.after(MARKER_OUTPUT, m, 1)
        self.assertIn("CONSULT: tests fail", grabbed)
        self.assertIn("CONTEXT: tried", grabbed)
        self.assertNotIn("CODE: KeyError", grabbed)

    def test_intent_from_marker_remainder(self):
        out = "some answer\nINTENT_FINALIZED: A tiny CLI for tracking coffee."
        self.assertEqual(text.intent_from(out, "original idea"), "A tiny CLI for tracking coffee.")

    def test_intent_from_keeps_rest_of_paragraph(self):
        # bash took the marker line plus following lines (`grep -A 50`);
        # match that for one-paragraph intents, stopping at a blank line.
        out = ("Q: for whom?\nINTENT_FINALIZED: A tiny CLI for tracking coffee.\n"
               "It runs offline and stores notes in a JSON file.\n"
               "\nSome afterthought paragraph.")
        self.assertEqual(
            text.intent_from(out, "x"),
            "A tiny CLI for tracking coffee.\nIt runs offline and stores notes in a JSON file.")

    def test_intent_from_falls_back_to_idea_when_no_marker(self):
        self.assertEqual(text.intent_from("no marker here", "original idea"), "original idea")

    def test_head_truncates_lines(self):
        self.assertEqual(text.head("a\nb\nc", 2), "a\nb")


SPEC_REPLY = """\
Here is the spec for the requested project.

# Spec

A tiny HTTP server in Python, stdlib only.

## Features

- GET / returns a hello page
"""


class DocExtraction(unittest.TestCase):
    """phase1/phase2 save spec.md/issues.md from model text output."""

    def test_unwrap_fenced_output(self):
        self.assertEqual(text.unwrap_fences("```markdown\n# Spec\nbody\n```"),
                         "# Spec\nbody")
        self.assertEqual(text.unwrap_fences("```\nplain\n```"), "plain")

    def test_unwrap_leaves_unfenced_output_alone(self):
        self.assertEqual(text.unwrap_fences("# Spec\nbody"), "# Spec\nbody")
        self.assertEqual(text.unwrap_fences("```python\ncode\n```\nmore"),
                         "```python\ncode\n```\nmore")

    def test_spec_doc_keeps_output_with_a_heading(self):
        self.assertIn("# Spec", text.spec_doc(SPEC_REPLY))
        self.assertIn("hello page", text.spec_doc(SPEC_REPLY))

    def test_spec_doc_rejects_reply_without_heading(self):
        # the never_spec stub reply — not a spec document
        self.assertIsNone(text.spec_doc("sorry, cannot write a spec right now"))
        self.assertIsNone(text.spec_doc(""))

    def test_spec_doc_unwraps_before_checking(self):
        fenced = "```\n# Spec\nstdlib only\n```"
        self.assertEqual(text.spec_doc(fenced), "# Spec\nstdlib only")

    def test_issues_doc_starts_at_first_issue_header(self):
        doc = text.issues_doc(SPEC_REPLY + "\n## Issue #1: Add server\nImplement it.\n")
        self.assertTrue(doc.startswith("## Issue #1"))
        self.assertNotIn("Here is the spec", doc)

    def test_issues_doc_rejects_output_without_issues(self):
        self.assertIsNone(text.issues_doc("# Spec but no issues here"))
        self.assertIsNone(text.issues_doc(""))

    def test_spec_doc_rejects_document_containing_code_fences(self):
        # Live run #4: GLM answered the idea with the whole program as text;
        # the "### How to use it:" heading inside the ```python fence defeated
        # the heading check and the code dump was saved as spec.md.
        dump = ("Here is a tiny CLI. Save this in caesar.py.\n\n"
                "```python\nimport argparse\n\ndef main():\n    print('hi')\n```\n\n"
                "### How to use it:\n\n```bash\npython caesar.py\n```")
        self.assertIsNone(text.spec_doc(dump))


if __name__ == "__main__":
    unittest.main()