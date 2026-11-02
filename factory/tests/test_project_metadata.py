"""Visible project names are local metadata independent of Git paths."""
import tempfile
import unittest
from pathlib import Path

from pipeline import project_metadata


class ProjectMetadataTests(unittest.TestCase):
    def test_title_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(project_metadata.read_name(project, 'old-key'), 'old-key')
            project_metadata.write_name(project, '  Mi investigación  ')
            self.assertEqual(project_metadata.read_name(project, 'old-key'), 'Mi investigación')
            for invalid in ('', 'a/b', 'a\\b', 'x\nnew', 'x' * 81):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    project_metadata.validate_name(invalid)

    def test_symlinked_metadata_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            project.mkdir()
            outside = Path(directory) / 'outside'
            outside.write_text('keep')
            evidence = project / '.siesta'
            evidence.mkdir()
            (evidence / 'display-name.txt').symlink_to(outside)
            with self.assertRaises(RuntimeError):
                project_metadata.write_name(project, 'New name')
            self.assertEqual(outside.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
