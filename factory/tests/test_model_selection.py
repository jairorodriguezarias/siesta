import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import __main__, pi
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

    def test_issue_review_agent_route_resolves(self):
        selection = normalize_selection({
            "agents": {"issue_review": {"integration-reviewer": {
                "model": "issue-review-model", "provider": "ollama"}}},
        }, role_defaults=DEFAULTS)
        self.assertEqual(resolve_route(selection, "issue_review", "integration-reviewer",
                                       "consultant"),
                         {"model": "issue-review-model", "provider": "ollama"})


class ProjectPersistence(unittest.TestCase):
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
