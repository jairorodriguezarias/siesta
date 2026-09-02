import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()