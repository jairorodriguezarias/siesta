import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import pi
from pipeline.pi import ROLE, build_args


class ModelConfig(unittest.TestCase):
    def test_roles_loaded_from_models_json(self):
        # Design routing: GLM-5.2 plans/consults (text protocol), local gemma4
        # codes. qwen2.5-coder was retired as worker: Ollama returns its tool
        # calls as text content instead of native tool_calls (ollama#12174,
        # fix PR #14162 unmerged), so the worker could not execute tools.
        # GLM obeying the last human message (runs #3/#4) is fixed by the
        # directive-last prompt shape in phases.py, not by the model choice.
        self.assertEqual(ROLE["planner"]["model"], "glm-5.2:cloud")
        # Worker model is routing policy (see config/models.json) — assert
        # it is set and consistent with the config file, not frozen to a name.
        from pipeline.pi import _config
        self.assertEqual(ROLE["worker"]["model"], _config["worker"]["model"])
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


class InteractiveTimeout(unittest.TestCase):
    """#35: the interactive interview gets the same timeout as #10 — a
    hung pi/Ollama call in phase 0 must not freeze the pipeline forever."""

    class _HangPopen:
        def __init__(self, *a, **kw):
            self.stdout = iter(())          # EOF immediately: no output at all
            self.pid = 424242
            self.returncode = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self, timeout=None):
            import subprocess
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd=["pi"], timeout=timeout)
            return 0

        def kill(self):
            self.returncode = -9

    def test_hung_interactive_call_times_out_and_returns_empty(self):
        import subprocess as sp
        from unittest.mock import patch
        with patch.object(sp, "Popen", self._HangPopen), \
             patch.dict(pi.__dict__, {"PI_TIMEOUT": 0.2}):
            out = pi.run_pi("planner", "b", "u", interactive=True)
        self.assertEqual(out, "")

    def test_interactive_wait_passes_the_timeout(self):
        import subprocess as sp
        from unittest.mock import patch
        seen = {}

        class P(self._HangPopen):
            def wait(self, timeout=None):
                seen["timeout"] = timeout
                raise sp.TimeoutExpired(cmd=["pi"], timeout=timeout)

        with patch.object(sp, "Popen", P), \
             patch.dict(pi.__dict__, {"PI_TIMEOUT": 0.2}):
            pi.run_pi("planner", "b", "u", interactive=True)
        self.assertEqual(seen["timeout"], 0.2)


class StderrSeparation(unittest.TestCase):
    """Hardening: stderr is provider noise, not model answer — the pomodoro
    run's verify_output.txt carried a pi warning inside the parsed text."""

    def _result(self, stdout: str, stderr: str):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)

    def test_only_stdout_is_parsed(self):
        import subprocess as sp
        from unittest.mock import patch
        with patch.object(sp, "run", return_value=self._result(
                "VERIFY_PASSED: fine", "Warning: Model not found, using custom id")):
            out = pi.run_pi("worker", "b", "u", thinking="off")
        self.assertEqual(out, "VERIFY_PASSED: fine")

    def test_stderr_marker_cannot_falsify_the_verdict(self):
        import subprocess as sp
        from unittest.mock import patch
        with patch.object(sp, "run", return_value=self._result(
                "I am not sure this runs.", "VERIFY_PASSED: noise from pi")):
            out = pi.run_pi("worker", "b", "u", thinking="off")
        self.assertEqual(out, "I am not sure this runs.")

    def test_stderr_persisted_below_separator(self):
        import subprocess as sp
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            artifact = Path(d) / "out.txt"
            with patch.object(sp, "run", return_value=self._result(
                    "real answer", "provider chatter")):
                pi.run_pi("worker", "b", "u", thinking="off", artifact=artifact)
            saved = artifact.read_text()
        self.assertTrue(saved.startswith("real answer"))
        self.assertIn("PROVIDER_LOG:", saved)
        self.assertIn("provider chatter", saved)


class ServedContext(unittest.TestCase):
    """Round-8: pi's catalog window vs Ollama's real served context —
    a silent mismatch truncated long worker prompts (#3/#4 blocked)."""

    def _ps(self, models_json):
        """Fake /api/ps response: a context manager whose read() gives bytes."""
        raw = models_json.encode()

        class _Body:
            def read(self):
                return raw

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Body()

    def test_probe_reads_served_context_for_the_routed_model(self):
        import urllib.request
        from unittest.mock import patch
        body = self._ps('{"models": [{"name": "gemma4:latest",'
                        ' "context_length": 8192}]}')
        with patch.object(urllib.request, "urlopen", return_value=body):
            self.assertEqual(pi._served_context("gemma4:latest"), 8192)

    def test_probe_accepts_bare_list_shape(self):
        import urllib.request
        from unittest.mock import patch
        body = self._ps('[{"name": "gemma4:latest", "context_length": 4096}]')
        with patch.object(urllib.request, "urlopen", return_value=body):
            self.assertEqual(pi._served_context("gemma4:latest"), 4096)

    def test_probe_returns_none_when_model_not_loaded(self):
        import urllib.request
        from unittest.mock import patch
        body = self._ps('{"models": [{"name": "glm-5.2:cloud",'
                        ' "context_length": 1000000}]}')
        with patch.object(urllib.request, "urlopen", return_value=body):
            self.assertIsNone(pi._served_context("gemma4:latest"))

    def test_probe_returns_none_on_unreadable_output(self):
        import urllib.request
        from unittest.mock import patch
        with patch.object(urllib.request, "urlopen",
                          return_value=self._ps("not json")):
            self.assertIsNone(pi._served_context("gemma4:latest"))
        with patch.object(urllib.request, "urlopen",
                          return_value=self._ps('{"models": [{"name": "gemma4"}]}')):
            self.assertIsNone(pi._served_context("gemma4:latest"))

    def test_probe_returns_none_when_ollama_absent(self):
        import urllib.error
        import urllib.request
        from unittest.mock import patch
        with patch.object(urllib.request, "urlopen",
                          side_effect=urllib.error.URLError("refused")):
            self.assertIsNone(pi._served_context("gemma4:latest"))

    def test_declared_context_reads_the_pi_catalog(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            catalog = Path(d) / "models.json"
            catalog.write_text('{"providers": {"ollama": {"models": ['
                               '{"id": "gemma4:latest", "contextWindow": 8192}]}}}')
            with patch.object(pi, "PI_CATALOG", catalog):
                self.assertEqual(pi._declared_context("gemma4:latest"), 8192)

    def test_declared_context_none_when_catalog_or_model_missing(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            with patch.object(pi, "PI_CATALOG", Path(d) / "nope.json"):
                self.assertIsNone(pi._declared_context("gemma4:latest"))
            catalog = Path(d) / "models.json"
            catalog.write_text('{"providers": {"ollama": {"models": []}}}')
            with patch.object(pi, "PI_CATALOG", catalog):
                self.assertIsNone(pi._declared_context("anything"))

    def test_mismatch_warns_when_served_smaller_than_declared(self):
        from unittest.mock import patch
        with patch.object(pi, "_served_context", return_value=8192), \
                patch.object(pi, "warn") as w:
            warned = pi.warn_if_context_mismatch("gemma4:latest", 131072)
        self.assertTrue(warned)
        w.assert_called_once()
        self.assertIn("gemma4:latest", w.call_args[0][0])
        self.assertIn("8192", w.call_args[0][0])

    def test_match_stays_silent(self):
        from unittest.mock import patch
        with patch.object(pi, "_served_context", return_value=8192), \
                patch.object(pi, "warn") as w:
            warned = pi.warn_if_context_mismatch("gemma4:latest", 8192)
        self.assertFalse(warned)
        w.assert_not_called()

    def test_unprobeable_stays_silent(self):
        from unittest.mock import patch
        with patch.object(pi, "_served_context", return_value=None), \
                patch.object(pi, "warn") as w:
            self.assertFalse(pi.warn_if_context_mismatch("gemma4:latest", 131072))
        w.assert_not_called()
        with patch.object(pi, "_served_context", return_value=8192), \
                patch.object(pi, "warn") as w:
            self.assertFalse(pi.warn_if_context_mismatch("gemma4:latest", None))
        w.assert_not_called()


class BuildArgs(unittest.TestCase):
    def test_non_interactively_flags_skills_and_prompt_shape(self):
        args = build_args(
            "worker", body="You are a developer.", user="do the thing",
            skills=(pi.SKILLS / "test-driven-development", pi.FACTORY_SKILLS / "kb-manager"),
            thinking="off")
        pi_bin, i = pi.PI_BIN, args
        self.assertEqual(i[0], pi_bin)
        self.assertEqual(i[1], "-p")                      # non-interactive
        self.assertEqual(i[i.index("--model") + 1], ROLE["worker"]["model"])
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