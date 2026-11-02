import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import __main__, pi, repository
from pipeline.model_selection import (PHASES, load_project, normalize_selection,
                                      resolve_route, save_project)


DEFAULTS = {
    "planner": {"model": "planner-default", "provider": "ollama"},
    "worker": {"model": "worker-default", "provider": "ollama"},
    "consultant": {"model": "consultant-default", "provider": "ollama"},
}


class RouteResolution(unittest.TestCase):
    def test_phase_and_agent_route_wins_over_phase_and_role_defaults(self):
        selection = normalize_selection({
            "phases": {"planning": {"model": "phase-model", "provider": "local"}},
            "agents": {"planning": {"planner": {
                "model": "agent-model", "provider": "cloud"}}},
        }, role_defaults=DEFAULTS)
        self.assertEqual(resolve_route(selection, "planning", "planner", "planner"),
                         {"model": "agent-model", "provider": "cloud"})

    def test_phase_route_wins_over_role_default(self):
        selection = normalize_selection({
            "phases": {"interview": {"model": "phase-model", "provider": "ollama"}},
        }, role_defaults=DEFAULTS)
        self.assertEqual(resolve_route(selection, "interview", "planner", "planner"),
                         {"model": "phase-model", "provider": "ollama"})

    def test_phase_route_reaches_the_actual_pi_arguments(self):
        selection = normalize_selection({
            "phases": {"interview": {"model": "local-interviewer", "provider": "ollama"}},
        }, role_defaults=DEFAULTS)
        args = pi.build_args("planner", "idea", "ask a question",
                             phase_name="interview", selection=selection)
        self.assertEqual(args[args.index("--model") + 1], "local-interviewer")
        self.assertEqual(args[args.index("--provider") + 1], "ollama")
        self.assertIn("Pipeline phase: interview", args[-1])

    def test_agent_route_reaches_the_actual_pi_arguments(self):
        selection = normalize_selection({
            "phases": {"planning": {"model": "phase", "provider": "ollama"}},
            "agents": {"planning": {"planner": {"model": "agent", "provider": "cloud"}}},
        }, role_defaults=DEFAULTS)
        args = pi.build_args("planner", "spec", "write issues",
                             phase_name="planning", selection=selection)
        self.assertEqual(args[args.index("--model") + 1], "agent")
        self.assertEqual(args[args.index("--provider") + 1], "cloud")

    def test_missing_overrides_use_snapshotted_role_defaults(self):
        selection = normalize_selection({}, role_defaults=DEFAULTS)
        self.assertEqual(resolve_route(selection, "verification", "worker", "worker"),
                         DEFAULTS["worker"])

    def test_selection_does_not_mutate_supplied_defaults(self):
        original = json.loads(json.dumps(DEFAULTS))
        normalize_selection({"phases": {"planning": {
            "model": "new", "provider": "ollama"}}}, role_defaults=DEFAULTS)
        self.assertEqual(DEFAULTS, original)

    def test_invalid_phase_or_agent_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown phase"):
            normalize_selection({"phases": {"unknown": {
                "model": "x", "provider": "ollama"}}}, role_defaults=DEFAULTS)
        with self.assertRaisesRegex(ValueError, "unknown agent"):
            normalize_selection({"agents": {"planning": {"tester": {
                "model": "x", "provider": "ollama"}}}}, role_defaults=DEFAULTS)

    def test_malformed_route_or_schema_is_rejected(self):
        for payload in (
                {"phases": {"planning": {"model": "x"}}},
                {"agents": {"planning": {"planner": "x"}}},
                {"version": 2},
                {"unexpected": True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_selection(payload, role_defaults=DEFAULTS)

    def test_empty_resolver_input_is_not_silently_replaced_by_defaults(self):
        with self.assertRaisesRegex(ValueError, "requires defaults"):
            pi.build_args("planner", "idea", "ask", selection={})

    def test_phase_catalog_is_explicit_and_nonempty(self):
        self.assertIn("interview", PHASES)
        self.assertIn("verification", PHASES)
        self.assertIn("issue_review", PHASES)
        self.assertIn("intent_review", PHASES)
        self.assertIn("design_repair", PHASES)

    def test_issue_review_agent_route_resolves(self):
        selection = normalize_selection({
            "agents": {"issue_review": {"integration-reviewer": {
                "model": "issue-review-model", "provider": "ollama"}}},
        }, role_defaults=DEFAULTS)
        self.assertEqual(resolve_route(selection, "issue_review", "integration-reviewer",
                                       "consultant"),
                         {"model": "issue-review-model", "provider": "ollama"})

    def test_intent_critic_route_reaches_the_actual_pi_arguments(self):
        selection = normalize_selection({
            "agents": {"intent_review": {"intent-critic": {
                "model": "intent-critic-model", "provider": "cloud"}}},
        }, role_defaults=DEFAULTS)
        args = pi.build_args("consultant", "request and answers", "Review intent",
                             phase_name="intent_review", agent="intent-critic",
                             context_kind="intent_review", tools="no", isolated=True,
                             selection=selection)
        self.assertEqual(args[args.index("--model") + 1], "intent-critic-model")
        self.assertEqual(args[args.index("--provider") + 1], "cloud")

    def test_design_specialist_route_reaches_the_actual_pi_arguments(self):
        selection = normalize_selection({
            "agents": {"design_review": {"design-simplicity-reviewer": {
                "model": "design-review-model", "provider": "ollama"}}},
        }, role_defaults=DEFAULTS)
        args = pi.build_args("consultant", "intent spec plan", "Review simplicity",
                             phase_name="design_review",
                             agent="design-simplicity-reviewer", context_kind="design",
                             tools="no", isolated=True, selection=selection)
        self.assertEqual(args[args.index("--model") + 1], "design-review-model")
        self.assertEqual(args[args.index("--provider") + 1], "ollama")

    def test_design_repair_route_reaches_the_actual_pi_arguments(self):
        selection = normalize_selection({
            "agents": {"design_repair": {"planner": {
                "model": "repair-model", "provider": "cloud"}}},
        }, role_defaults=DEFAULTS)
        args = pi.build_args("planner", "intent and documents", "Repair",
                             phase_name="design_repair", agent="planner",
                             context_kind="design_repair", tools="no", isolated=True,
                             selection=selection)
        self.assertEqual(args[args.index("--model") + 1], "repair-model")
        self.assertEqual(args[args.index("--provider") + 1], "cloud")


class ProjectPersistence(unittest.TestCase):
    def test_changed_route_creates_revision_and_invalidates_saved_approvals(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            original = normalize_selection({}, role_defaults=DEFAULTS)
            changed = normalize_selection({"phases": {"planning": {
                "model": "another-model", "provider": "ollama"}}},
                role_defaults=DEFAULTS)
            save_project(project, original)
            checkpoint = project / ".pipeline-checkpoint"
            checkpoint.write_text("complete\n")
            (project / "verify_verdict.txt").write_text("VERIFY_PASSED\n")
            repository.save_state(project, {"reviewed_product": "old",
                                            "verified_product": "old", "other": "kept"})
            save_project(project, changed)
            revisions = json.loads((project / ".siesta/model-selection-revisions.json").read_text())
            self.assertEqual(len(revisions), 1)
            self.assertEqual(revisions[0]["previous"], original)
            self.assertEqual(revisions[0]["current"], changed)
            self.assertTrue(__main__._invalidate_model_approvals(
                project, original, changed, checkpoint))
            self.assertEqual(checkpoint.read_text().strip(), "phase-2")
            self.assertFalse((project / "verify_verdict.txt").exists())
            self.assertEqual(repository.load_state(project), {"other": "kept"})
            save_project(project, changed)
            self.assertEqual(len(json.loads((project / ".siesta/model-selection-revisions.json").read_text())), 1)

    def test_project_selection_round_trips_without_changing_global_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selection = normalize_selection({
                "phases": {"interview": {"model": "local-qwen", "provider": "ollama"}},
            }, role_defaults=DEFAULTS)
            path = save_project(project, selection)
            self.assertEqual(path, project / ".siesta" / "model-selection.json")
            self.assertEqual(load_project(project), selection)
            self.assertEqual(DEFAULTS["planner"]["model"], "planner-default")

    def test_missing_saved_selection_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_project(Path(directory)))

    def test_invalid_saved_selection_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            path = project / ".siesta" / "model-selection.json"
            path.parent.mkdir()
            path.write_text('{"version": 99}')
            with self.assertRaisesRegex(ValueError, "version"):
                load_project(project)

    def test_cli_resume_uses_the_saved_project_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selection = normalize_selection({
                "phases": {"interview": {
                    "model": "pinned-interview", "provider": "ollama"}},
            }, role_defaults=DEFAULTS)
            save_project(project, selection)
            args = type("Args", (), {"model_selection": None, "proj": project})()
            self.assertEqual(__main__._selection_for_project(args), selection)

    def test_saved_route_is_used_and_recorded_for_a_project_call(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selection = normalize_selection({
                "phases": {"interview": {
                    "model": "pinned-interview", "provider": "ollama"}},
            }, role_defaults=DEFAULTS)
            save_project(project, selection)
            command = [sys.executable, "-c", "print('answer')"]
            with patch.object(pi, "build_args", return_value=command) as builder:
                answer = pi.run_pi("planner", "idea", "ask", cwd=project,
                                   phase_name="interview")
            self.assertEqual(answer.strip(), "answer")
            builder.assert_called_once()
            record = json.loads((project / ".siesta" / "calls.jsonl")
                                .read_text().splitlines()[0])
            self.assertEqual(record["model"], "pinned-interview")
            self.assertEqual(record["phase"], "interview")


if __name__ == "__main__":
    unittest.main()
