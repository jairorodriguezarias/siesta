"""Review budgets persist and count only active review work."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from pipeline import reviews


def report(verdict="pass", findings=None):
    return json.dumps({"version": 1, "verdict": verdict,
                       "summary": "Independent review of the evidence",
                       "findings": findings or []})


FINDING = {"id": "F1", "severity": "major", "target": "R1",
           "evidence": "A concrete failure", "requested_fix": "Correct R1"}
CONTEXT = {"included": ["spec.md", "source.py"], "omitted": []}


class ReviewBudgetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)

    def test_policy_is_pinned_and_deep_has_larger_budget(self):
        self.assertEqual(reviews.pin_project_policy(self.project, "deep"), "deep")
        self.assertEqual(reviews.project_policy(self.project), "deep")
        session = reviews.ReviewSession(self.project, "deep-issue", policy="deep")
        self.assertEqual(session.state["budget"]["call_limit"], 40)
        self.assertEqual(session.state["budget"]["active_seconds_limit"], 7200)
        with self.assertRaisesRegex(reviews.ReviewError, "fixed"):
            reviews.pin_project_policy(self.project, "normal")

    def test_call_limit_survives_resume_and_blocks_retry(self):
        session = reviews.ReviewSession(self.project, "budget-issue")
        session.state["budget"]["calls_used"] = 19
        session._save()
        session.start_round("v1")
        attempt = session.begin_attempt(agent="reviewer", context=CONTEXT)
        session.finish_attempt(attempt, response="invalid")
        resumed = reviews.ReviewSession(self.project, "budget-issue")
        self.assertEqual(resumed.state["budget"]["calls_used"], 20)
        with self.assertRaisesRegex(reviews.ReviewError, "budget exhausted"):
            resumed.begin_attempt(agent="reviewer", context=CONTEXT,
                                  retry_reason="reviewer_failure")
        self.assertEqual(resumed.state["status"], "blocked")

    def test_user_wait_between_calls_does_not_consume_active_seconds(self):
        session = reviews.ReviewSession(self.project, "waiting-issue")
        session.start_round("v1")
        attempt = session.begin_attempt(agent="reviewer", context=CONTEXT)
        session.finish_attempt(attempt, response=report())
        recorded = session.state["budget"]["active_seconds"]
        time.sleep(0.03)
        resumed = reviews.ReviewSession(self.project, "waiting-issue")
        self.assertEqual(resumed.state["budget"]["active_seconds"], recorded)
        self.assertIsNone(resumed.state["budget"].get("repair_started_at"))

    def test_interrupted_repair_keeps_spent_call_without_counting_downtime(self):
        session = reviews.ReviewSession(self.project, "interrupted-repair")
        session.start_round("v1")
        attempt = session.begin_attempt(agent="reviewer", context=CONTEXT)
        session.finish_attempt(attempt, response=report("findings", [FINDING]))
        session.begin_repair_call()
        calls = session.state["budget"]["calls_used"]
        active = session.state["budget"]["active_seconds"]
        time.sleep(0.03)
        resumed = reviews.ReviewSession(self.project, "interrupted-repair")
        self.assertEqual(resumed.state["budget"]["calls_used"], calls)
        self.assertEqual(resumed.state["budget"]["active_seconds"], active)
        resumed.record_repair("v2", ["regression"], evidence="Recovered repair")
        self.assertEqual(resumed.state["budget"]["calls_used"], calls)

    def test_repair_proxy_and_adjudication_consume_calls(self):
        repair = reviews.ReviewSession(self.project, "repair")
        repair.start_round("v1")
        attempt = repair.begin_attempt(agent="reviewer", context=CONTEXT)
        repair.finish_attempt(attempt, response=report("findings", [FINDING]))
        repair.begin_repair_call()
        repair.record_repair("v2", ["regression"], evidence="Fixed R1")
        self.assertEqual(repair.state["budget"]["calls_used"], 2)

        proxy = reviews.ReviewSession(self.project, "proxy")
        proxy.start_round("v1", reviewers=("reviewer",), external_approver="proxy")
        attempt = proxy.begin_attempt(agent="reviewer", context=CONTEXT)
        proxy.finish_attempt(attempt, response=report())
        proxy.begin_external_call()
        proxy.record_external_decision("proxy", approved=True, evidence="Approved")
        self.assertEqual(proxy.state["budget"]["calls_used"], 2)

        dispute = reviews.ReviewSession(self.project, "dispute")
        dispute.start_round("v1")
        attempt = dispute.begin_attempt(agent="reviewer", context=CONTEXT)
        dispute.finish_attempt(attempt, response=report("findings", [FINDING]))
        dispute.record_counterevidence("F1", "Independent test contradicts this")
        number = dispute.begin_adjudication("F1", agent="adjudicator", context=CONTEXT)
        dispute.finish_adjudication("F1", number, verdict="dismissed",
                                    evidence="Independent evidence resolves it")
        self.assertEqual(dispute.state["budget"]["calls_used"], 2)

    def test_active_time_limit_blocks_before_new_call(self):
        session = reviews.ReviewSession(self.project, "time-issue")
        session.start_round("v1")
        session.state["budget"]["active_seconds"] = 3600
        session._save()
        with self.assertRaisesRegex(reviews.ReviewError, "active-time budget exhausted"):
            session.begin_attempt(agent="reviewer", context=CONTEXT)
        self.assertEqual(session.state["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
