"""Guard #17: factory skill docs must only reference CLIs that exist.

The bash era left 30+ `kb-manager.sh` calls behind after the Python port;
models following the skills verbatim hit a failing command. This test pins
the real repo skills (not the SIESTA_FACTORY fake) to the shim."""
import os
import re
import unittest
from pathlib import Path

REAL_SKILLS = Path(__file__).resolve().parent.parent / "skills"

DELETED_CLIS = ("kb-manager.sh", "learn.sh", "run-pipeline.sh",
                "pre-issue.sh", "post-issue.sh", "learn-issue.sh")

SUPPORTED_KB_COMMANDS = {"query", "append-node", "append-edge",
                         "get-node", "list-all", "init-project"}


class FactorySkillDocs(unittest.TestCase):
    def test_no_references_to_deleted_bash_clis(self):
        for f in sorted(REAL_SKILLS.rglob("SKILL.md")):
            content = f.read_text()
            for stale in DELETED_CLIS:
                self.assertNotIn(stale, content,
                                 f"{f.name} in {f.parent.name} still "
                                 f"references the deleted {stale}")

    def test_kb_shim_subcommands_are_supported(self):
        for f in sorted(REAL_SKILLS.rglob("SKILL.md")):
            for m in re.finditer(r"python3 -m pipeline\.kb (\S+)",
                                 f.read_text()):
                self.assertIn(m.group(1), SUPPORTED_KB_COMMANDS,
                              f"{f.parent.name} calls unsupported shim "
                              f"command {m.group(1)!r}")


class ChildEnv(unittest.TestCase):
    def test_child_env_puts_factory_on_pythonpath(self):
        from pipeline import pi
        env = pi._child_env()
        self.assertIn(str(pi.FACTORY), env["PYTHONPATH"].split(os.pathsep))


if __name__ == "__main__":
    unittest.main()