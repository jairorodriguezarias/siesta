import tempfile
import unittest
from pathlib import Path

from pipeline import skill_versions


def put_skill(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(content)
    return path


class ProjectSkillPins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.project = base / "project"
        self.factory = base / "factory-skills"
        self.adapted = base / "adapted-skills"
        self.factory.mkdir()
        self.adapted.mkdir()
        self.roots = {"factory": self.factory, "adapted": self.adapted}
        self.skill = put_skill(self.factory, "executor", "FIRST_VERSION\n")
        put_skill(self.adapted, "review", "ADAPTED_VERSION\n")

    def test_project_snapshots_factory_and_adapted_skills(self):
        manifest = skill_versions.pin_project(self.project, roots=self.roots)
        self.assertEqual({(item["scope"], item["name"]) for item in manifest["skills"]},
                         {("factory", "executor"), ("adapted", "review")})
        stored = self.project / ".siesta/skills/factory/executor/SKILL.md"
        self.assertEqual(stored.read_text(), "FIRST_VERSION\n")
        self.assertEqual(skill_versions.pinned_skill(self.project, "review", scope="adapted"),
                         "ADAPTED_VERSION\n")

    def test_resume_uses_original_snapshot_after_active_skill_changes(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        (self.skill / "SKILL.md").write_text("CHANGED_DURING_RUN\n")

        mapped = skill_versions.resolve_paths(
            self.project, (self.skill,), roots=self.roots)
        resumed = skill_versions.pin_project(self.project, roots=self.roots)

        self.assertEqual((mapped[0] / "SKILL.md").read_text(), "FIRST_VERSION\n")
        first_hash = next(item["sha256"] for item in resumed["skills"]
                          if item["scope"] == "factory" and item["name"] == "executor")
        second = skill_versions.pin_project(self.project, roots=self.roots)
        second_hash = next(item["sha256"] for item in second["skills"]
                           if item["scope"] == "factory" and item["name"] == "executor")
        self.assertEqual(first_hash, second_hash)
        self.assertEqual((self.skill / "SKILL.md").read_text(), "CHANGED_DURING_RUN\n")

    def test_skill_added_after_start_cannot_sneak_into_current_run(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        added = put_skill(self.factory, "late-addition", "LATE\n")
        with self.assertRaisesRegex(RuntimeError, "added after this run was pinned"):
            skill_versions.resolve_paths(self.project, (added,), roots=self.roots)

    def test_modified_snapshot_fails_closed_on_resume(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        snapshot = self.project / ".siesta/skills/factory/executor/SKILL.md"
        snapshot.write_text("TAMPERED\n")
        with self.assertRaisesRegex(RuntimeError, "snapshot changed"):
            skill_versions.pin_project(self.project, roots=self.roots)

    def test_manifest_symlink_is_rejected(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        manifest = self.project / ".siesta/skill-versions.json"
        manifest.unlink()
        outside = Path(self.tmp.name) / "outside.json"
        outside.write_text('{"version":1,"skills":[]}')
        manifest.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "not a regular file"):
            skill_versions.pin_project(self.project, roots=self.roots)

    def test_malformed_manifest_fails_closed(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        manifest = self.project / ".siesta/skill-versions.json"
        manifest.write_text("[]")
        with self.assertRaisesRegex(RuntimeError, "unsupported format"):
            skill_versions.pin_project(self.project, roots=self.roots)

    def test_trusted_root_symlink_alias_cannot_bypass_snapshot_mapping(self):
        skill_versions.pin_project(self.project, roots=self.roots)
        alias = self.factory / "executor-alias"
        alias.symlink_to(self.skill, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "cannot traverse symlinks"):
            skill_versions.resolve_paths(self.project, (alias,), roots=self.roots)


if __name__ == "__main__":
    unittest.main()
