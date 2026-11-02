import json
import importlib
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pipeline import agents
from pipeline import pi
from pipeline.pi import build_args


class AgentDefinitions(unittest.TestCase):
    def test_existing_model_roles_have_loadable_agent_definitions(self):
        for agent_id, role in (("planner", "planner"), ("worker", "worker"),
                               ("consultant", "consultant")):
            with self.subTest(agent=agent_id):
                agent = agents.get_agent(agent_id, model_role=role)
                self.assertIn(f"# Agent: {agent_id}", agents.load_definition(agent))
                self.assertTrue(agent.allowed_contexts)
                self.assertTrue(agent.response_format)

    def test_pi_prompt_identifies_agent_and_includes_loaded_definition(self):
        args = build_args("worker", "Task context", "Implement the issue")
        prompt = args[-1]
        self.assertIn("Agent identity: worker", prompt)
        self.assertIn("Invocation context category: pipeline", prompt)
        self.assertIn("Registered response format:", prompt)
        self.assertIn("Implement the assigned issue", prompt)
        self.assertTrue(prompt.endswith("Task context\n\nImplement the issue"))

    def test_isolated_prompt_includes_definition_without_enabling_discovery(self):
        args = build_args("consultant", "Evidence", "Return JSON",
                          tools="no", isolated=True)
        prompt = args[-1]
        self.assertIn("Agent identity: consultant", prompt)
        self.assertIn("independent advice", prompt)
        for flag in ("--no-context-files", "--no-extensions", "--no-skills",
                     "--no-prompt-templates", "--no-session"):
            self.assertIn(flag, args)
        self.assertIn("--system-prompt", args)

    def test_missing_required_definition_fails_before_invocation(self):
        agent = agents.AGENTS["worker"]
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(agents.AGENTS, worker=replace(
                    agent, definition_path=Path(directory) / "missing.md")):
            with self.assertRaisesRegex(RuntimeError, "definition.*missing"):
                build_args("worker", "context", "directive")

    def test_invalid_required_definition_fails_before_invocation(self):
        agent = agents.AGENTS["worker"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.md"
            path.write_text("# Agent: planner\n\nWrong identity.\n")
            with patch.dict(agents.AGENTS, worker=replace(agent, definition_path=path)):
                with self.assertRaisesRegex(RuntimeError, "definition.*invalid"):
                    build_args("worker", "context", "directive")

    def test_call_record_identifies_the_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-c", "print('answer')"]
            with patch.object(pi, "build_args", return_value=command):
                answer = pi.run_pi("worker", "context", "directive",
                                   cwd=Path(directory), agent="worker")
            self.assertEqual(answer.strip(), "answer")
            record = json.loads((Path(directory) / ".siesta" / "calls.jsonl")
                                .read_text().splitlines()[0])
            self.assertEqual(record["agent"], "worker")

    def test_selected_factory_supplies_the_agent_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = Path(directory)
            (factory / "agents").mkdir()
            for source in agents.AGENT_DIR.glob("*.md"):
                (factory / "agents" / source.name).write_text(source.read_text())
            try:
                with patch.dict(os.environ, {"SIESTA_FACTORY": str(factory)}):
                    importlib.reload(agents)
                    self.assertEqual(agents.AGENT_DIR, factory / "agents")
                    self.assertIn("# Agent: planner",
                                  agents.load_definition(agents.AGENTS["planner"]))
            finally:
                importlib.reload(agents)


class AgentPermissions(unittest.TestCase):
    def test_design_reviewers_have_separate_tool_free_lenses(self):
        expected = {"design-comprehension-reviewer", "design-simplicity-reviewer",
                    "design-readiness-reviewer"}
        for agent_id in expected:
            with self.subTest(agent=agent_id):
                agent = agents.get_agent(agent_id, model_role="consultant",
                                         context_kind="design")
                self.assertEqual(agent.allowed_tools, ())
                self.assertIn("independent", agents.load_definition(agent).lower())
                args = build_args("consultant", "intent spec plan", "Review design",
                                  agent=agent_id, context_kind="design",
                                  phase_name="design_review", tools="no", isolated=True)
                self.assertIn("Agent identity: " + agent_id, args[-1])
                self.assertIn("--no-context-files", args)

    def test_planner_can_receive_only_the_explicit_design_repair_context(self):
        agent = agents.get_agent("planner", model_role="planner",
                                 context_kind="design_repair")
        self.assertEqual(agent.allowed_tools, ())
        args = build_args("planner", "approved intent and documents", "Repair design",
                          agent="planner", context_kind="design_repair",
                          phase_name="design_repair", tools="no", isolated=True)
        self.assertIn("Agent identity: planner", args[-1])
        self.assertIn("--no-tools", args)

    def test_intent_critic_has_an_isolated_tool_free_context(self):
        agent = agents.get_agent("intent-critic", model_role="consultant",
                                 context_kind="intent_review")
        self.assertEqual(agent.allowed_tools, ())
        self.assertIn("original request", agents.load_definition(agent))
        args = build_args("consultant", "request and answers", "Review intent",
                          agent="intent-critic", context_kind="intent_review",
                          phase_name="intent_review", tools="no", isolated=True)
        self.assertIn("Agent identity: intent-critic", args[-1])
        self.assertIn("--no-context-files", args)

    def test_review_specialists_are_separate_tool_free_agents(self):
        for agent_id in ("integration-reviewer", "quality-reviewer"):
            with self.subTest(agent=agent_id):
                agent = agents.get_agent(agent_id, model_role="consultant",
                                         context_kind="review")
                self.assertEqual(agent.allowed_tools, ())
                self.assertIn("# Agent: " + agent_id, agents.load_definition(agent))
                args = build_args("consultant", "contract and code", "Review",
                                  agent=agent_id, context_kind="review", tools="no")
                self.assertIn("Agent identity: " + agent_id, args[-1])
                self.assertIn("--no-tools", args)

    def test_default_tools_are_bounded_by_registry_policy(self):
        args = build_args("worker", "context", "directive")
        self.assertEqual(args[args.index("--tools") + 1],
                         ",".join(agents.AGENTS["worker"].allowed_tools))

    def test_consultant_has_no_tools_by_default(self):
        args = build_args("consultant", "evidence", "advise")
        self.assertIn("--no-tools", args)
        self.assertNotIn("--tools", args)

    def test_requested_tool_outside_agent_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not allowed for agent worker"):
            build_args("worker", "context", "directive", tools="delete")

    def test_declaring_tools_in_markdown_cannot_grant_them(self):
        agent = agents.AGENTS["planner"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.md"
            path.write_text(
                "# Agent: planner\n\n## Role\nPlanner.\n\n"
                "## Context allowed\nPlans.\n\n## Response format\nText.\n\n"
                "## Tool policy\nYou may use delete.\n")
            with patch.dict(agents.AGENTS, planner=replace(agent, definition_path=path)):
                with self.assertRaisesRegex(ValueError, "not allowed for agent planner"):
                    build_args("planner", "context", "directive", tools="delete")

    def test_agent_cannot_claim_another_model_role_or_context(self):
        with self.assertRaisesRegex(ValueError, "uses model role planner"):
            build_args("worker", "context", "directive", agent="planner")
        with self.assertRaisesRegex(ValueError, "context.*not allowed"):
            build_args("worker", "context", "directive", context_kind="interview")


if __name__ == "__main__":
    unittest.main()
