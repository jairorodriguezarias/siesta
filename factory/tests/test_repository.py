"""Repository state is proven by real Git commits, not completion prose."""
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline import phases, repository
from pipeline.kb import Graph


class RepositoryState(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.proj = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.git('init', '-q')
        self.kb = Graph(self.proj / 'kb/graph.json')
        (self.proj / '.gitignore').write_text('ignored.txt\n')
        (self.proj / 'issues.md').write_text('## Issue #1: Answer\nReturn 42 with tests.\n')
        (self.proj / 'answer.py').write_text('answer = 42\n')
        repository.commit(self.proj, 'Initial plan')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.proj, check=True,
                              capture_output=True, text=True).stdout

    def reject_commits(self):
        hook = self.proj / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)

    def test_failed_issue_commit_preserves_work_without_false_completion(self):
        before = self.git('rev-parse', 'HEAD')
        self.reject_commits()
        (self.proj / 'answer.py').write_text('answer = 43\n')
        with self.assertRaisesRegex(RuntimeError, 'commit'):
            phases.post_issue(self.proj, 1, 'Implemented the requested answer.', self.kb)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual((self.proj / 'answer.py').read_text(), 'answer = 43\n')
        self.assertFalse(self.kb.query(type_='decision'))
        self.assertNotIn('Issue #1 completed', self.git('show', ':kb/graph.json'))

    def test_only_committed_completion_is_a_ledger_entry(self):
        self.kb.node('decision', 'Issue #1 completed', 'Uncommitted claim')
        self.assertEqual(repository.completed_issues(self.proj), set())

    def test_changed_or_removed_completed_issue_is_rejected(self):
        phases.post_issue(self.proj, 1, 'Implemented the requested answer.', self.kb)
        self.assertEqual(repository.completed_issues(self.proj), {1})
        for new_plan in ('## Issue #1: Answer\nReturn 43 with tests.\n',
                         '## Issue #2: New task\nKeep previous work.\n'):
            (self.proj / 'issues.md').write_text(new_plan)
            with self.assertRaisesRegex(RuntimeError, 'completed issue #1'):
                repository.completed_issues(self.proj)

    def test_legacy_completion_uses_plan_at_first_committed_record(self):
        self.kb.node('decision', 'Issue #1 completed', 'Legacy plain text record')
        repository.commit(self.proj, 'Legacy completion')
        (self.proj / 'issues.md').write_text('## Issue #1: Revised\nReturn 99.\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'Externally revised requirements')
        with self.assertRaisesRegex(RuntimeError, 'completed issue #1'):
            repository.completed_issues(self.proj)

    def test_duplicate_numbers_fail_instead_of_overwriting_work(self):
        with (self.proj / 'issues.md').open('a') as out:
            out.write('\n## Issue #1: Duplicate\nAnother request.\n')
        with self.assertRaisesRegex(RuntimeError, 'Duplicate issue #1'):
            repository.completed_issues(self.proj)

    def test_fenced_acceptance_code_is_part_of_immutable_requirement(self):
        plan = '## Issue #1: Answer\n```python\nassert answer() == 42\n## Issue #99\n```\n'
        (self.proj / 'issues.md').write_text(plan)
        repository.commit(self.proj, 'Acceptance example')
        phases.post_issue(self.proj, 1, 'Implemented the requested answer.', self.kb)
        self.assertEqual(list(repository.read_plan(self.proj)), [1])
        (self.proj / 'issues.md').write_text(plan.replace('== 42', '== 99'))
        with self.assertRaisesRegex(RuntimeError, 'completed issue #1'):
            repository.completed_issues(self.proj)

    def test_uncommitted_completion_claim_cannot_be_adopted(self):
        self.kb.node('decision', 'Issue #1 completed', 'Uncommitted old claim')
        with self.assertRaisesRegex(RuntimeError, 'completion ledger'):
            repository.adopt_changes(self.proj)
        self.assertNotIn('Issue #1 completed', self.git('show', 'HEAD:kb/graph.json'))

    def test_dirty_product_is_preserved_until_explicit_adoption(self):
        note = self.proj / 'human notes.txt'
        note.write_text('Keep this work\n')
        self.kb.node('learning', 'Local bookkeeping', 'Not product')
        with self.assertRaisesRegex(RuntimeError, 'adopt-changes'):
            repository.require_clean(self.proj)
        self.assertEqual(note.read_text(), 'Keep this work\n')
        repository.adopt_changes(self.proj)
        repository.require_clean(self.proj)
        self.assertEqual(self.git('show', 'HEAD:human notes.txt'), 'Keep this work\n')

    def test_fingerprint_includes_requirements_and_modes_but_not_kb(self):
        original = repository.fingerprint(self.proj)
        self.kb.node('learning', 'Bookkeeping', 'New detail')
        (self.proj / 'ignored.txt').write_text('Runtime evidence')
        repository.commit(self.proj, 'Bookkeeping only')
        self.assertEqual(repository.fingerprint(self.proj), original)
        (self.proj / 'answer.py').chmod(0o755)
        self.assertNotEqual(repository.fingerprint(self.proj), original)
        (self.proj / 'answer.py').chmod(0o644)
        (self.proj / 'issues.md').write_text('## Issue #1: Changed requirement\n')
        self.assertNotEqual(repository.fingerprint(self.proj), original)

    def test_file_deletion_and_rename_are_valid_product_changes(self):
        (self.proj / 'answer.py').rename(self.proj / 'renamed.py')
        repository.commit(self.proj, 'Rename product module')
        self.assertIn('renamed.py', self.git('ls-files'))
        (self.proj / 'renamed.py').unlink()
        repository.commit(self.proj, 'Remove obsolete module')
        self.assertNotIn('renamed.py', self.git('ls-files'))
        repository.require_clean(self.proj)

    def test_removing_plan_cannot_bypass_completed_requirements(self):
        phases.post_issue(self.proj, 1, 'Implemented the answer.', self.kb)
        before = self.git('rev-parse', 'HEAD')
        (self.proj / 'issues.md').unlink()
        with self.assertRaisesRegex(RuntimeError, 'completed issue'):
            repository.adopt_changes(self.proj)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)


if __name__ == '__main__':
    unittest.main()
