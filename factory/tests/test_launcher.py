"""The real shell entry point must report the routing used by Python."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FACTORY = Path(__file__).resolve().parent.parent


class LauncherRouting(unittest.TestCase):
    def test_reports_default_and_overridden_factory_routing(self):
        for override in (False, True):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "source" / "factory"
                shutil.copytree(FACTORY / "pipeline", source / "pipeline")
                (source / "bin").mkdir()
                launcher = source / "bin" / "siesta.sh"
                shutil.copyfile(FACTORY / "bin" / "siesta.sh", launcher)
                active = root / "local profile" / "factory" if override else source
                (active / "config").mkdir(parents=True)
                routes = {role: {"model": f"local-{role}:latest", "provider": "ollama"}
                          for role in ("planner", "worker", "consultant")}
                (active / "config" / "models.json").write_text(json.dumps(routes))
                project = active / "projects" / "routing-check"
                project.mkdir(parents=True)
                (project / ".pipeline-checkpoint").write_text("phase-2\n")
                (project / "issues.md").write_text("## Issue #1: Check routing\n")
                (project / "stop.md").write_text("Stop before any model call.\n")
                env = {**os.environ,
                       "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
                env.pop("SIESTA_FACTORY", None)
                if override:
                    env["SIESTA_FACTORY"] = str(active)
                run = subprocess.run(["bash", str(launcher), "--auto", "--resume", "routing check"],
                                     cwd=root, env=env, capture_output=True, text=True, timeout=45)
                output = run.stdout + run.stderr
                self.assertEqual(run.returncode, 0, output)
                self.assertIn("Model configuration: " + os.path.relpath(
                    active / "config" / "models.json", root), output)
                for role, route in routes.items():
                    self.assertIn(f"{role}: {route['model']} (provider: {route['provider']})", output)
                self.assertNotIn("GLM-5.2", output)
                self.assertNotIn("Gemma4 31B", output)


if __name__ == "__main__":
    unittest.main()
