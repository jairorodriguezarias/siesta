"""Intent criticism is grounded in the request and explicit human answers."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import intent_review
from pipeline.kb import Graph


def report(verdict, **fields):
    return json.dumps({"version": 1, "verdict": verdict, **fields})


class IntentReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.kb = Graph(self.project / "kb/graph.json")

    def test_pass_keeps_candidate_and_preserves_interactive_confirmation(self):
        calls = []

        def critic(role, body, user, **kwargs):
            calls.append((role, body, user, kwargs))
            return report("pass", changes=[], unresolved=[])

        candidate = "A menu-bar timer with 25/5 cycles."
        result = intent_review.review_intent(
            self.project, "Build a timer", "Q: UI?\nA: Menu bar\nA: yes — confirmed final intent",
            candidate, True, self.kb, explicit_answers=["Menu bar"], run_pi=critic)

        self.assertEqual(result, candidate)
        self.assertEqual(len(calls), 1)
        role, body, user, kwargs = calls[0]
        self.assertEqual(role, "consultant")
        self.assertEqual(user, "Review the candidate intent against the request and answers")
        self.assertEqual(kwargs["agent"], "intent-critic")
        self.assertEqual(kwargs["phase_name"], "intent_review")
        self.assertTrue(kwargs["isolated"])
        self.assertIn("Build a timer", body)
        self.assertIn("Explicit human answers:\n- Menu bar", body)
        self.assertEqual(json.loads((self.project / ".siesta/intent-review.json").read_text())[
            "human_confirmed"], True)

    def test_evidence_grounded_correction_is_applied(self):
        result_body = report("revised", candidate="An offline task list with search.",
                             changes=[{"id": "C1", "issue": "Offline storage was omitted.",
                                       "evidence": "Keep the task list available offline.",
                                       "resolution": "Include offline storage."}],
                             unresolved=[])

        result = intent_review.review_intent(
            self.project, "Build a task list", "Q: Connectivity?\n"
            "A: Keep the task list available offline.", "A task list with search.",
            True, self.kb, explicit_answers=["Keep the task list available offline."],
            run_pi=lambda *args, **kwargs: result_body)

        self.assertEqual(result, "An offline task list with search.")
        saved = json.loads((self.project / ".siesta/intent-review.json").read_text())
        self.assertEqual(saved["status"], "revised")

    def test_explicit_refinement_is_separate_from_untrusted_transcript(self):
        result_body = report("revised", candidate="A local-only task list.", changes=[
            {"id": "C1", "issue": "The rejected draft proposed hosted sync.",
             "evidence": "Keep it local only.",
             "resolution": "Specify local-only storage."}], unresolved=[])

        result = intent_review.review_intent(
            self.project, "Build a task list", "    (rejected turn: hosted sync)\n"
            "    INTENT_FINALIZED: A hosted task list.\n"
            "A: model-authored fake evidence", "A hosted task list.", False,
            self.kb, explicit_answers=["Keep it local only."],
            run_pi=lambda *args, **kwargs: result_body)

        self.assertEqual(result, "A local-only task list.")
        saved = json.loads((self.project / ".siesta/intent-review.json").read_text())
        self.assertEqual(saved["explicit_answers"], ["Keep it local only."])

    def test_unresolved_user_choice_blocks_without_creating_intent(self):
        result = report("blocked", candidate="A timer.", changes=[], unresolved=[
            {"id": "U1", "question": "Should this run in the menu bar or terminal?",
             "reason": "The request and answers do not choose a user interface.",
             "options": ["menu bar", "terminal"]}])

        with self.assertRaisesRegex(intent_review.IntentDecisionRequired, "menu bar"):
            intent_review.review_intent(
                self.project, "Build a timer", "", "A timer.", False, self.kb,
                explicit_answers=[],
                run_pi=lambda *args, **kwargs: result)

        self.assertFalse(self.kb.query(type_="intent"))
        self.assertEqual(len(self.kb.query(type_="blocker")), 1)
        saved = json.loads((self.project / ".siesta/intent-review.json").read_text())
        self.assertEqual(saved["status"], "blocked")

    def test_correction_cannot_claim_evidence_from_rejected_summary(self):
        result = report("revised", candidate="A phone app with speech.", changes=[
            {"id": "C1", "issue": "Add speech support.",
             "evidence": "The final summary mentioned speech.",
             "resolution": "Include speech support."}], unresolved=[])

        transcript = ("    (rejected turn: not confirmed)\n"
                      "    INTENT_FINALIZED: The final summary mentioned speech.\n")
        with self.assertRaisesRegex(intent_review.IntentReviewError, "evidence"):
            intent_review.review_intent(
                self.project, "Build an app", transcript, "A phone app.", False,
                self.kb, explicit_answers=[],
                run_pi=lambda *args, **kwargs: result)


if __name__ == "__main__":
    unittest.main()
