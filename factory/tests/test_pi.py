import unittest
from pathlib import Path

from pipeline import pi
from pipeline.pi import ROLE, build_args


class ModelConfig(unittest.TestCase):
    def test_roles_loaded_from_models_json(self):
        # Design routing: GLM-5.2 plans/consults (text protocol), local qwen codes.
        # GLM obeying the last human message (runs #3/#4) is fixed by the
        # directive-last prompt shape in phases.py, not by the model choice.
        self.assertEqual(ROLE["planner"]["model"], "glm-5.2:cloud")
        self.assertEqual(ROLE["worker"]["model"], "qwen2.5-coder:latest")
        self.assertEqual(ROLE["consultant"]["model"], "glm-5.2:cloud")
        self.assertEqual(ROLE["consultant"]["provider"], "ollama")


class Timeout(unittest.TestCase):
    """#10: a hung pi call is "no answer", never a frozen pipeline."""

    def test_timed_out_call_returns_empty(self):
        import subprocess as sp
        from unittest.mock import patch
        with patch.object(sp, "run", side_effect=sp.TimeoutExpired(cmd=["pi"], timeout=1)):
            self.assertEqual(
                pi.run_pi("worker", "b", "u", thinking="off"), "")

    def test_timeout_is_configurable(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"SIESTA_PI_TIMEOUT": "7"}):
            import importlib
            from pipeline import pi as pi_mod
            importlib.reload(pi_mod)
            try:
                self.assertEqual(pi_mod.PI_TIMEOUT, 7)
            finally:
                importlib.reload(pi_mod)


class BuildArgs(unittest.TestCase):
    def test_non_interactively_flags_skills_and_prompt_shape(self):
        args = build_args(
            "worker", body="You are a developer.", user="do the thing",
            skills=(pi.SKILLS / "test-driven-development", pi.FACTORY_SKILLS / "kb-manager"),
            thinking="off")
        pi_bin, i = pi.PI_BIN, args
        self.assertEqual(i[0], pi_bin)
        self.assertEqual(i[1], "-p")                      # non-interactive
        self.assertEqual(i[i.index("--model") + 1], "qwen2.5-coder:latest")
        self.assertEqual(i[i.index("--provider") + 1], "ollama")
        self.assertEqual(i[i.index("--thinking") + 1], "off")
        self.assertEqual(i[i.index("--skill") + 1],
                         str(pi.SKILLS / "test-driven-development") + "/")
        self.assertEqual(i[i.index("--skill", i.index("--skill") + 1) + 1],
                         str(pi.FACTORY_SKILLS / "kb-manager") + "/")
        self.assertEqual(i[-1],
                         "You are a developer.\n\ndo the thing")  # body+user merged (#23)

    def test_skill_dirs_keep_trailing_slash_like_bash(self):
        args = build_args("planner", body="b", user="u",
                          skills=(pi.SKILLS / "interview-me",), thinking="off")
        self.assertEqual(str(args[args.index("--skill") + 1]).rstrip("/") + "/",
                         str(pi.SKILLS / "interview-me") + "/")

    def test_thinking_is_always_explicit(self):
        args = build_args("consultant", body="b", user="u", thinking="high")
        self.assertEqual(args[args.index("--thinking") + 1], "high")

    def test_thinking_high_survives_for_thinking_models(self):
        # glm-5.2:cloud supports thinking — the requested level is forwarded.
        args = build_args("consultant", body="b", user="u", thinking="high")
        self.assertEqual(args[args.index("--thinking") + 1], "high")

    def test_thinking_never_reaches_non_thinking_models(self):
        # #24: qwen2.5-coder 400s on any thinking level; even a caller
        # requesting "high" (deep diagnosis) must be pinned to "off".
        args = build_args("worker", body="b", user="u", thinking="high")
        self.assertEqual(args[args.index("--thinking") + 1], "off")

    def test_no_tools_flag_for_text_protocol_calls(self):
        args = build_args("worker", body="b", user="u", tools="no")
        self.assertIn("--no-tools", args)

    def test_tools_allowlist_flag_name(self):
        args = build_args("planner", body="b", user="u", tools="write")
        self.assertEqual(args[args.index("--tools") + 1], "write")

    def test_default_leaves_tools_untouched(self):
        args = build_args("worker", body="b", user="u")
        self.assertNotIn("--no-tools", args)
        self.assertNotIn("--tools", args)


if __name__ == "__main__":
    unittest.main()