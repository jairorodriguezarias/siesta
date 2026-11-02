"""Legacy project migration preserves the committed completion ledger."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import issue_reviews, migration, model_selection, repository, reviews
from pipeline.pi import ROLE
from pipeline.source_context import gather
from pipeline.kb import Graph


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.com"], check=True)
        (self.project / ".gitignore").write_text(".siesta/\n")
        (self.project / "spec.md").write_text("# Spec\n- R1: Return a greeting.\n")
        (self.project / "issues.md").write_text("## Issue #1: Greeting\nReturn a greeting.\n")
        self.graph = Graph(self.project / "kb/graph.json")
        self.graph.node("intent", "Intent", "A greeting")
        self.base = repository.commit(self.project, "Initial plan")
        (self.project / "source.py").write_text("def greet():\n    return 'hello'\n")
        body = repository.read_plan(self.project)[1]
        self.graph.node("decision", "Issue #1 completed", json.dumps({
            "issue_sha256": repository.issue_digest(body), "output": "Done"}))
        repository.commit(self.project, "Issue #1 implemented")
        evidence = self.project / ".siesta"
        evidence.mkdir()
        (evidence / "skill-versions.json").write_text("{}\n")
        (evidence / "model-selection.json").write_text(json.dumps(
            model_selection.normalize_selection({}, role_defaults=ROLE)))
        (evidence / "review-policy.json").write_text('{"policy":"normal"}\n')

    def test_active_legacy_issue_is_revalidated_without_reimplementation_or_duplicate_record(self):
        record = migration.prepare(self.project, was_existing=True,
                                   was_complete=False, legacy_configuration=True)
        self.assertEqual(record["pending_issue_reviews"], [1])
        self.assertEqual(len(record["skill_versions_sha256"]), 64)
        self.assertEqual(migration._issue_base(self.project, 1), self.base)
        before_head = repository.checked_git(self.project, "rev-parse", "HEAD")
        before_nodes = len(self.graph.query())
        def suite(project, number):
            self.assertEqual(number, 1)
            (project / ".siesta/tests.json").write_text('{"status":"passed"}')
            return "passed"
        with patch.object(migration.issue_reviews, "review_issue", return_value=True) as review:
            updated = migration.revalidate_completed(
                self.project, record, run_regression=suite,
                run_pi=lambda *_args, **_kwargs: "", gather_fn=lambda *_args: "")
        self.assertEqual(updated["status"], "complete")
        self.assertEqual(updated["pending_issue_reviews"], [])
        self.assertEqual(repository.completed_issues(self.project), {1})
        self.assertEqual(len(self.graph.query()), before_nodes)
        self.assertEqual(repository.checked_git(self.project, "rev-parse", "HEAD"), before_head)
        self.assertEqual(review.call_args.args[3], self.base)

    def test_failed_revalidation_keeps_issue_pending(self):
        record = migration.prepare(self.project, was_existing=True,
                                   was_complete=False, legacy_configuration=True)
        with patch.object(migration.issue_reviews, "review_issue") as review:
            with self.assertRaisesRegex(RuntimeError, "failed its regression suite"):
                migration.revalidate_completed(
                    self.project, record, run_regression=lambda *_: "failed",
                    run_pi=lambda *_args, **_kwargs: "", gather_fn=lambda *_args: "")
            review.assert_not_called()
        saved = json.loads((self.project / migration.MIGRATION_FILE).read_text())
        self.assertEqual(saved["pending_issue_reviews"], [1])

    def test_stale_approval_does_not_satisfy_migration(self):
        issue = repository.read_plan(self.project)[1]
        reviewers = ("integration-reviewer",)
        config = issue_reviews._issue_review_configuration(
            self.project, 1, issue, reviewers)
        identity = hashlib.sha256(
            f"1:{repository.issue_digest(issue)}:{self.base}:{config}".encode()
        ).hexdigest()[:60]
        path = self.project / ".siesta/reviews" / f"issue-1-{identity}.json"
        path.parent.mkdir()
        version = issue_reviews._issue_review_version(
            self.project, 1, issue, self.base, config)
        path.write_text(json.dumps({"status": "approved", "approved_version": "old",
                                    "policy_name": reviews.project_policy(self.project),
                                    "rounds": [{"status": "clean", "version": version}]}))
        self.assertFalse(migration._approved_issue_review(self.project, 1))
        path.write_text(json.dumps({"status": "approved", "approved_version": version,
                                    "policy_name": reviews.project_policy(self.project),
                                    "rounds": [{"status": "clean", "version": version}]}))
        self.assertTrue(migration._approved_issue_review(self.project, 1))
        (self.project / "source.py").write_text("def greet():\n    return 'hello, world'\n")
        self.assertTrue(migration._approved_issue_review(self.project, 1))

    def test_legacy_revalidation_runs_real_issue_review_gate_with_fake_pi(self):
        record = migration.prepare(self.project, was_existing=True,
                                   was_complete=False, legacy_configuration=True)
        calls = []
        def suite(project, _number):
            (project / ".siesta/tests.json").write_text('{"status":"passed"}')
            return "passed"
        def invoke(_role, prompt, *_args, **_kwargs):
            calls.append(prompt)
            return json.dumps({"version": 1, "verdict": "pass",
                               "summary": "The greeting requirement is implemented and tested.",
                               "findings": []})
        updated = migration.revalidate_completed(
            self.project, record, run_regression=suite,
            run_pi=invoke, gather_fn=gather)
        self.assertEqual(updated["status"], "complete")
        self.assertEqual(len(calls), 1)
        self.assertIn("Return a greeting", calls[0])
        self.assertEqual(repository.completed_issues(self.project), {1})

    def test_finished_legacy_project_records_pin_without_revalidation(self):
        record = migration.prepare(self.project, was_existing=True,
                                   was_complete=True, legacy_configuration=True)
        self.assertEqual(record["status"], "finished")
        self.assertEqual(record["pending_issue_reviews"], [])
        self.assertEqual(migration.revalidate_completed(
            self.project, record, run_regression=lambda *_: self.fail("must not run"),
            run_pi=lambda *_args, **_kwargs: "", gather_fn=lambda *_args: ""), record)


if __name__ == "__main__":
    unittest.main()
