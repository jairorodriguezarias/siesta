"""Ollama/Pi discovery and explicit compatibility checks."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import model_catalog, model_selection


class ModelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.factory = Path(self.temp.name)
        (self.factory / "config").mkdir()
        (self.factory / "config" / "models.json").write_text(json.dumps({
            "planner": {"model": "cloud:cloud", "provider": "ollama"},
            "worker": {"model": "local:latest", "provider": "ollama"},
            "consultant": {"model": "cloud:cloud", "provider": "ollama"}}))

    def test_mixed_catalog_distinguishes_advertised_installed_registered_and_validated(self):
        registered = {"cloud:cloud", "local:latest", "pi-only:latest"}
        installed = {"cloud:cloud": {"remote_host": "https://ollama.com"},
                     "local:latest": {"size": 42},
                     "ollama-only:latest": {"size": 99}}
        with patch.object(model_catalog, "_registered_models", return_value=(registered, None)), \
             patch.object(model_catalog, "_installed_models", return_value=(installed, None)):
            rows = {row["id"]: row for row in model_catalog.catalog(self.factory)["models"]}
        self.assertEqual(rows["cloud:cloud"]["origin"], "cloud")
        self.assertEqual(rows["local:latest"]["origin"], "local")
        self.assertTrue(rows["cloud:cloud"]["advertised"])
        self.assertTrue(rows["local:latest"]["installed"])
        self.assertFalse(rows["ollama-only:latest"]["pi_registered"])
        self.assertFalse(rows["pi-only:latest"]["installed"])
        self.assertFalse(rows["cloud:cloud"]["validated"])
        self.assertIn("Register", rows["ollama-only:latest"]["preparation"])

    def test_ollama_unavailable_still_shows_pi_and_default_routes(self):
        with patch.object(model_catalog, "_registered_models", return_value=({"pi-only"}, None)), \
             patch.object(model_catalog, "_installed_models", return_value=({}, "Ollama unavailable")):
            result = model_catalog.catalog(self.factory)
        self.assertFalse(result["ollama_available"])
        self.assertIn("cloud:cloud", {row["id"] for row in result["models"]})
        self.assertTrue(all(not row["installed"] for row in result["models"]))

    def test_unregistered_model_never_invokes_pi(self):
        with patch.object(model_catalog, "catalog", return_value={"models": [{
                "id": "local:latest", "pi_registered": False, "installed": True}]}), \
             patch.object(model_catalog, "run_pi") as invoke:
            result = model_catalog.check_compatibility(self.factory, model="local:latest")
        self.assertEqual(result["status"], "needs_setup")
        invoke.assert_not_called()

    def test_auth_failure_and_tool_incompatibility_are_explicit(self):
        listing = {"models": [{"id": "cloud:cloud", "pi_registered": True,
                               "installed": True}]}
        with patch.object(model_catalog, "catalog", return_value=listing), \
             patch.object(model_catalog, "run_pi", return_value=""):
            failed = model_catalog.check_compatibility(self.factory, model="cloud:cloud")
        self.assertEqual(failed["status"], "incompatible")
        self.assertIn("authentication", failed["reason"])
        with patch.object(model_catalog, "catalog", return_value=listing), \
             patch.object(model_catalog, "run_pi", side_effect=["SIESTA_MODEL_READY", "Done"]):
            failed = model_catalog.check_compatibility(self.factory, model="cloud:cloud")
        self.assertEqual(failed["status"], "incompatible")
        self.assertFalse(failed["tools"])
        self.assertIn("native write tool", failed["reason"])

    def test_native_write_uses_temp_dir_and_exact_requested_route(self):
        listing = {"models": [{"id": "local:latest", "pi_registered": True,
                               "installed": True}]}
        roots = []
        def invoke(role, *_args, **kwargs):
            root = kwargs["cwd"]
            roots.append(root)
            selection = model_selection.load_project(root)
            phase = kwargs["phase_name"]
            self.assertEqual(selection["phases"][phase]["model"], "local:latest")
            if role == "worker":
                (root / "model-tool-proof.txt").write_text("SIESTA_TOOL_READY\n")
                return "Completed"
            return "SIESTA_MODEL_READY"
        with patch.object(model_catalog, "catalog", return_value=listing), \
             patch.object(model_catalog, "run_pi", side_effect=invoke):
            result = model_catalog.check_compatibility(self.factory, model="local:latest")
        self.assertEqual(result["status"], "compatible")
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0], roots[1])
        self.assertFalse(roots[0].exists())


if __name__ == "__main__":
    unittest.main()
