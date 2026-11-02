"""Persistent review policy, evidence and repair limits."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.reviews import ReviewError, ReviewSession


def report(verdict="pass", findings=None):
    return json.dumps({
        "version": 1,
        "verdict": verdict,
        "summary": "Reviewed the supplied implementation and evidence.",
        "findings": findings or [],
    })


def finding(identifier="F1"):
    return {
        "id": identifier,
        "severity": "major",
        "target": "R1 / app.py:12",
        "evidence": "The implementation returns the wrong value for empty input.",
        "requested_fix": "Return an empty list for empty input.",
    }


def begin(session, version="v1", report_text=None):
    session.start_round(version)
    attempt = session.begin_attempt(
        agent="code-reviewer",
        context={"included": ["app.py", "tests/test_app.py"], "omitted": []},
    )
    session.finish_attempt(attempt, response=report_text or report())
    return attempt


class ReviewReports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.session = ReviewSession(self.project, "issue-1")

    def tearDown(self):
        self.temp.cleanup()

    def test_report_schema_requires_evidence_and_requested_fix(self):
        invalid = report("findings", [{**finding(), "evidence": ""}])
        self.session.start_round("v1")
        attempt = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": []},
        )
        self.assertIsNone(self.session.finish_attempt(attempt, response=invalid))
        self.assertEqual(self.session.state["rounds"][-1]["attempts"][0]["status"],
                         "invalid")

    def test_invalid_report_gets_one_retry_then_blocks(self):
        self.session.start_round("v1")
        context = {"included": ["app.py"], "omitted": []}
        first = self.session.begin_attempt(agent="code-reviewer", context=context)
        self.session.finish_attempt(first, response="not json")
        second = self.session.begin_attempt(
            agent="code-reviewer", retry_reason="reviewer_failure", context=context)
        self.session.finish_attempt(second, response="still not json")
        self.assertEqual(self.session.state["status"], "blocked")
        self.assertEqual(self.session.state["rounds"][0]["attempts"][0]["response"],
                         "not json")
        with self.assertRaisesRegex(ReviewError, "blocked"):
            self.session.begin_attempt(agent="code-reviewer", context=context)

    def test_context_expansion_uses_the_single_retry(self):
        self.session.start_round("v1")
        first = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": ["tests"]},
        )
        self.session.finish_attempt(first, response=report("insufficient_evidence"))
        with self.assertRaisesRegex(ReviewError, "additional evidence"):
            self.session.begin_attempt(
                agent="code-reviewer", retry_reason="expanded_context",
                context={"included": ["app.py"], "omitted": ["tests"]},
            )
        second = self.session.begin_attempt(
            agent="code-reviewer", retry_reason="expanded_context",
            context={"included": ["app.py", "tests/test_app.py"], "omitted": []},
        )
        self.session.finish_attempt(second, response=report())
        self.assertEqual(self.session.state["status"], "approved")
        self.assertEqual(len(self.session.state["rounds"][0]["attempts"]), 2)

    def test_author_cannot_be_reviewer_and_empty_context_is_insufficient(self):
        self.session.start_round("v1")
        with self.assertRaisesRegex(ReviewError, "independent"):
            self.session.begin_attempt(
                agent="worker",
                context={"included": ["app.py"], "omitted": []},
            )
        with self.assertRaisesRegex(ReviewError, "context"):
            self.session.begin_attempt(
                agent="code-reviewer",
                context={"included": [], "omitted": ["app.py"]},
            )

    def test_unknown_report_fields_are_rejected(self):
        self.session.start_round("v1")
        attempt = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": []},
        )
        payload = json.loads(report())
        payload["approved"] = True
        self.assertIsNone(self.session.finish_attempt(attempt, response=json.dumps(payload)))
        self.assertEqual(self.session.state["rounds"][0]["attempts"][0]["status"],
                         "invalid")

    def test_oversized_invalid_report_keeps_preview_size_and_digest(self):
        self.session.start_round("v1")
        attempt = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": []},
        )
        raw = "x" * 256_001
        self.session.finish_attempt(attempt, response=raw)
        saved = self.session.state["rounds"][0]["attempts"][0]
        self.assertEqual(saved["response_preview"], raw[:4000])
        self.assertEqual(saved["response_chars"], len(raw))
        self.assertEqual(len(saved["response_sha256"]), 64)

    def test_duplicate_json_keys_are_invalid_reports(self):
        self.session.start_round("v1")
        attempt = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": []},
        )
        response = (
            '{"version":1,"verdict":"pass","verdict":"findings",'
            '"summary":"Review complete.","findings":[]}'
        )
        self.assertIsNone(self.session.finish_attempt(attempt, response=response))
        self.assertEqual(self.session.state["rounds"][0]["attempts"][0]["status"],
                         "invalid")

    def test_repeated_insufficient_evidence_blocks_approval(self):
        self.session.start_round("v1")
        attempt = self.session.begin_attempt(
            agent="code-reviewer",
            context={"included": ["app.py"], "omitted": ["tests"]},
        )
        self.session.finish_attempt(
            attempt, response=report("insufficient_evidence"))
        retry = self.session.begin_attempt(
            agent="code-reviewer", retry_reason="expanded_context",
            context={"included": ["app.py", "tests/test_app.py"], "omitted": []},
        )
        self.session.finish_attempt(
            retry, response=report("insufficient_evidence"))
        self.assertEqual(self.session.state["status"], "blocked")


class ReviewBudgets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_normal_policy_approves_after_one_clean_round(self):
        session = ReviewSession(self.project, "normal")
        begin(session)
        self.assertEqual(session.state["status"], "approved")
        self.assertEqual(session.state["policy"]["max_rounds"], 3)

    def test_deep_policy_needs_two_clean_rounds_on_same_version(self):
        session = ReviewSession(self.project, "deep", policy="deep")
        begin(session, "fingerprint-a")
        self.assertEqual(session.state["status"], "active")
        begin(session, "fingerprint-a")
        self.assertEqual(session.state["status"], "approved")

    def test_required_reviewer_group_needs_each_independent_pass(self):
        session = ReviewSession(self.project, "reviewer-group")
        reviewers = ("integration-reviewer", "quality-reviewer")
        session.start_round("fingerprint", reviewers=reviewers)
        context = {"included": ["spec.md", "app.py", "tests/test_app.py"], "omitted": []}
        first = session.begin_attempt(agent=reviewers[0], context=context)
        session.finish_attempt(first, response=report())
        self.assertEqual(session.state["status"], "active")
        second = session.begin_attempt(agent=reviewers[1], context=context)
        session.finish_attempt(second, response=report())
        self.assertEqual(session.state["status"], "approved")
        self.assertEqual(set(session.state["rounds"][0]["reviewer_reports"]), set(reviewers))

    def test_reviewer_group_aggregates_findings_and_keeps_attempts_per_agent(self):
        session = ReviewSession(self.project, "reviewer-findings")
        reviewers = ("integration-reviewer", "quality-reviewer")
        session.start_round("before", reviewers=reviewers)
        context = {"included": ["spec.md", "app.py"], "omitted": []}
        first = session.begin_attempt(agent=reviewers[0], context=context)
        session.finish_attempt(
            first, response=report("findings", [finding("F1")]))
        second = session.begin_attempt(agent=reviewers[1], context=context)
        session.finish_attempt(second, response=report())
        current = session.state["rounds"][0]
        self.assertEqual(current["status"], "findings")
        self.assertEqual(current["report"]["findings"][0]["id"],
                         "integration-reviewer/F1")

    def test_reviewer_group_retries_failure_for_the_same_reviewer_only(self):
        session = ReviewSession(self.project, "reviewer-retry-group")
        reviewers = ("integration-reviewer", "quality-reviewer")
        session.start_round("fingerprint", reviewers=reviewers)
        context = {"included": ["spec.md", "app.py"], "omitted": []}
        first = session.begin_attempt(agent=reviewers[0], context=context)
        session.finish_attempt(first, error="first reviewer unavailable")
        second = session.begin_attempt(agent=reviewers[1], context=context)
        session.finish_attempt(second, response=report())
        retry = session.begin_attempt(
            agent=reviewers[0], retry_reason="reviewer_failure", context=context)
        session.finish_attempt(retry, response=report())
        self.assertEqual(session.state["status"], "approved")

    def test_reviewer_group_resumes_after_insufficient_evidence(self):
        session = ReviewSession(self.project, "group-evidence-resume")
        reviewers = ("integration-reviewer", "quality-reviewer")
        session.start_round("fingerprint", reviewers=reviewers,
                            external_approver="consultant")
        attempt = session.begin_attempt(
            agent=reviewers[0], context={"included": ["app.py"], "omitted": ["tests"]})
        session.finish_attempt(attempt, response=report("insufficient_evidence"))

        resumed = ReviewSession(self.project, "group-evidence-resume")
        current = resumed.start_round("fingerprint", reviewers=reviewers,
                                      external_approver="consultant")
        self.assertEqual(current["status"], "insufficient_evidence")
        retry = resumed.begin_attempt(
            agent=reviewers[0], retry_reason="expanded_context",
            context={"included": ["app.py", "tests/test_app.py"], "omitted": []})
        resumed.finish_attempt(retry, response=report())
        second = resumed.begin_attempt(
            agent=reviewers[1],
            context={"included": ["app.py", "tests/test_app.py"], "omitted": []})
        resumed.finish_attempt(second, response=report())
        self.assertEqual(resumed.state["rounds"][0]["status"],
                         "awaiting_external_approval")

    def test_external_approval_waits_until_both_specialists_pass(self):
        session = ReviewSession(self.project, "proxy-gate")
        reviewers = ("integration-reviewer", "quality-reviewer")
        context = {"included": ["spec.md", "app.py"], "omitted": []}
        session.start_round("fingerprint", reviewers=reviewers,
                            external_approver="consultant")
        first = session.begin_attempt(agent=reviewers[0], context=context)
        session.finish_attempt(first, response=report())
        with self.assertRaisesRegex(ReviewError, "awaiting_external_approval"):
            session.record_external_decision(
                "consultant", approved=True, evidence="APPROVED: policy met")
        second = session.begin_attempt(agent=reviewers[1], context=context)
        session.finish_attempt(second, response=report())
        self.assertEqual(session.state["rounds"][0]["status"],
                         "awaiting_external_approval")
        self.assertEqual(session.state["status"], "active")
        session.record_external_decision(
            "consultant", approved=True, evidence="APPROVED: policy met")
        self.assertEqual(session.state["status"], "approved")

    def test_external_rejection_becomes_a_repairable_finding(self):
        session = ReviewSession(self.project, "proxy-repair")
        reviewers = ("integration-reviewer", "quality-reviewer")
        context = {"included": ["spec.md", "app.py"], "omitted": []}
        session.start_round("before", reviewers=reviewers,
                            external_approver="consultant")
        for agent in reviewers:
            attempt = session.begin_attempt(agent=agent, context=context)
            session.finish_attempt(attempt, response=report())
        session.record_external_decision(
            "consultant", approved=False,
            evidence="NEEDS_REVISION: add error handling.")
        self.assertEqual(session.state["rounds"][0]["status"], "findings")
        session.record_repair("after", ["tests"], evidence="Added error handling.")
        session.record_check("tests", "pytest passed", passed=True)
        session.start_round("after", reviewers=reviewers,
                            external_approver="consultant")

    def test_repair_requires_a_new_version_and_rechecking_affected_checks(self):
        session = ReviewSession(self.project, "repair")
        begin(session, "before", report("findings", [finding()]))
        with self.assertRaisesRegex(ReviewError, "new version"):
            session.record_repair("before", ["tests"], evidence="No version changed.")
        session.record_repair("after", ["tests", "lint"], evidence="Fixed empty input.")
        with self.assertRaisesRegex(ReviewError, "rerun"):
            session.start_round("after")
        session.record_check("tests", "pytest failed: 2 tests", passed=False)
        with self.assertRaisesRegex(ReviewError, "rerun"):
            session.start_round("after")
        session.record_check("tests", "pytest passed: 14 tests", passed=True)
        session.record_check("lint", "ruff passed", passed=True)
        session.start_round("after")
        self.assertEqual(session.state["rounds"][-1]["version"], "after")

    def test_counterevidence_requires_an_independent_adjudication(self):
        session = ReviewSession(self.project, "dispute")
        begin(session, "v1", report("findings", [finding()]))
        session.record_counterevidence("F1", "The edge case is covered in test_empty.")
        with self.assertRaisesRegex(ReviewError, "independent"):
            session.adjudicate("F1", verdict="dismissed", agent="worker",
                               evidence="Agreed.", context={
                                   "included": ["app.py", "tests/test_app.py"],
                                   "omitted": [],
                               })
        session.adjudicate("F1", verdict="dismissed", agent="code-reviewer",
                           evidence="The cited test covers this input.", context={
                               "included": ["app.py", "tests/test_app.py"],
                               "omitted": [],
                           })
        session.start_round("v1")
        self.assertEqual(session.state["rounds"][-1]["number"], 2)

    def test_adjudicator_failure_uses_one_retry(self):
        session = ReviewSession(self.project, "adjudicator-retry")
        begin(session, "v1", report("findings", [finding()]))
        session.record_counterevidence("F1", "The relevant test covers the input.")
        context = {"included": ["app.py", "tests/test_app.py"], "omitted": []}
        first = session.begin_adjudication("F1", agent="code-reviewer", context=context)
        self.assertFalse(session.finish_adjudication(
            "F1", first, error="independent reviewer timed out"))
        second = session.begin_adjudication("F1", agent="code-reviewer", context=context)
        self.assertTrue(session.finish_adjudication(
            "F1", second, verdict="dismissed",
            evidence="The cited test covers the disputed case."))
        self.assertEqual(
            session.state["rounds"][0]["disputes"]["F1"]["status"], "dismissed")

    def test_repair_budget_and_resume_state_are_preserved(self):
        session = ReviewSession(self.project, "resume")
        begin(session, "v1", report("findings", [finding()]))
        session.record_repair("v2", ["tests"], evidence="Fixed the reported behavior.")
        session.record_check("tests", "suite passed", passed=True)
        reopened = ReviewSession(self.project, "resume")
        self.assertEqual(reopened.state["repair_count"], 1)
        self.assertEqual(reopened.state["policy"]["max_repairs"], 2)
        self.assertEqual(reopened.state["repairs"][0]["post_version"], "v2")

    def test_reviewer_execution_failure_uses_one_retry(self):
        session = ReviewSession(self.project, "failed-call")
        session.start_round("v1")
        context = {"included": ["app.py"], "omitted": []}
        first = session.begin_attempt(agent="code-reviewer", context=context)
        session.finish_attempt(first, error="provider unavailable")
        second = session.begin_attempt(
            agent="code-reviewer", retry_reason="reviewer_failure", context=context)
        session.finish_attempt(second, response=report())
        self.assertEqual(session.state["status"], "approved")
        self.assertEqual(session.state["rounds"][0]["attempts"][0]["status"], "failed")

    def test_resume_after_interrupted_reviewer_call_preserves_retry_budget(self):
        session = ReviewSession(self.project, "interrupted")
        session.start_round("v1")
        context = {"included": ["app.py"], "omitted": []}
        session.begin_attempt(agent="code-reviewer", context=context)
        resumed = ReviewSession(self.project, "interrupted")
        retry = resumed.begin_attempt(
            agent="code-reviewer", retry_reason="reviewer_failure", context=context)
        resumed.finish_attempt(retry, response=report())
        self.assertEqual(resumed.state["status"], "approved")
        self.assertEqual(
            resumed.state["rounds"][0]["attempts"][0]["error"],
            "reviewer call did not finish before resume")

    def test_normal_round_limit_and_repair_limit_are_enforced(self):
        session = ReviewSession(self.project, "round-limit", policy="deep")
        for version in ("v1", "v2", "v3", "v4", "v5"):
            begin(session, version)
        self.assertEqual(session.state["status"], "active")
        with self.assertRaisesRegex(ReviewError, "maximum review rounds"):
            session.start_round("v6")
        self.assertEqual(session.state["status"], "blocked")

        repairs = ReviewSession(self.project, "repair-limit")
        begin(repairs, "v1", report("findings", [finding("F1")]))
        repairs.record_repair("v2", ["tests"], evidence="Repair one.")
        repairs.record_check("tests", "passed", passed=True)
        begin(repairs, "v2", report("findings", [finding("F2")]))
        repairs.record_repair("v3", ["tests"], evidence="Repair two.")
        repairs.record_check("tests", "passed", passed=True)
        begin(repairs, "v3", report("findings", [finding("F3")]))
        with self.assertRaisesRegex(ReviewError, "maximum review repairs"):
            repairs.record_repair("v4", ["tests"], evidence="Repair three.")
        self.assertEqual(repairs.state["status"], "blocked")

    def test_unknown_review_policy_and_path_traversal_are_rejected(self):
        with self.assertRaisesRegex(ReviewError, "policy"):
            ReviewSession(self.project, "bad", policy="unbounded")
        with self.assertRaisesRegex(ReviewError, "identifier"):
            ReviewSession(self.project, "../outside")


if __name__ == "__main__":
    unittest.main()
