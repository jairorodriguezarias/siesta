import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import __main__ as pipeline_main
from pipeline import phases


def _proj(test_body: str | None) -> Path:
    """Project dir; test_body=None → no test suite, else a pytest project."""
    proj = Path(tempfile.mkdtemp())
    if test_body is not None:
        (proj / "pyproject.toml").write_text("")
        (proj / "tests").mkdir()
        (proj / "tests" / "test_it.py").write_text(test_body)
    return proj


# Marker-less verify output — what qwen actually emitted in the live run
# (tool-speak instead of the VERIFY_PASSED:/VERIFY_FAILED: protocol).
DRIFTED = "Let me check the runtime with bash: {\"name\": \"bash\", \"command\": \"ls\"}"


class VerifyFallback(unittest.TestCase):
    """When the model emits no protocol marker, the regression suite decides."""

    def test_markerless_output_with_passing_tests_verifies_passed(self):
        proj = _proj("def test_ok():\n    assert True\n")
        with patch.object(phases, "run_pi", return_value=DRIFTED):
            self.assertEqual(phases.verify(proj), "VERIFY_PASSED")

    def test_markerless_output_with_failing_tests_verifies_failed(self):
        proj = _proj("def test_bad():\n    assert False\n")
        with patch.object(phases, "run_pi", return_value=DRIFTED):
            self.assertEqual(phases.verify(proj), "VERIFY_FAILED")

    def test_markerless_output_without_suite_stays_failed(self):
        proj = _proj(None)
        with patch.object(phases, "run_pi", return_value=DRIFTED):
            self.assertEqual(phases.verify(proj), "VERIFY_FAILED")

    def test_explicit_marker_wins_over_regression(self):
        # Primary signal stays strict: a passed marker never runs the fallback.
        proj = _proj("def test_bad():\n    assert False\n")
        with patch.object(phases, "run_pi", return_value="VERIFY_PASSED: runs fine"):
            self.assertEqual(phases.verify(proj), "VERIFY_PASSED")


class StartupContextGuard(unittest.TestCase):
    """Round-8: the startup guard warns on served < declared, once per
    routed model, and a broken probe never blocks a run from starting."""

    def test_guard_checks_each_distinct_routed_model_once(self):
        calls = []
        with patch.object(pipeline_main, "_declared_context",
                          return_value=131072), \
             patch.object(pipeline_main, "warn_if_context_mismatch",
                          side_effect=lambda m, d: calls.append(m) or False):
            pipeline_main._warn_context_mismatches()
        # planner and consultant share a model — dedupe leaves the distinct
        # routed models, in role order (config is the truth).
        from pipeline.pi import ROLE
        routed = [ROLE[r]["model"] for r in ("planner", "worker", "consultant")]
        self.assertEqual(calls, list(dict.fromkeys(routed)))

    def test_guard_silent_when_no_mismatch(self):
        with patch.object(pipeline_main, "_declared_context", return_value=None):
            pipeline_main._warn_context_mismatches()    # no probe, no warn

    def test_guard_never_crashes_a_run(self):
        def boom(model):
            raise RuntimeError("probe exploded")
        with patch.object(pipeline_main, "_declared_context", boom):
            pipeline_main._warn_context_mismatches()    # must not raise


if __name__ == "__main__":
    unittest.main()