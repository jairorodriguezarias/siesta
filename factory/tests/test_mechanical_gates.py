"""Real process/repository reproductions of false success and unsafe recovery."""
import os
import subprocess
import sys
import tarfile
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline import phases, pi
from pipeline.__main__ import GITIGNORE
from pipeline.kb import Graph


class VerifyEvidence(unittest.TestCase):
    def test_model_pass_cannot_override_failing_or_absent_tests(self):
        for suite in ('def test_failure():\n    assert False\n', None):
            with self.subTest(suite=suite), TemporaryDirectory() as directory:
                proj = Path(directory)
                (proj / 'main.py').write_text("print('ready')\n")
                if suite:
                    (proj / 'test_main.py').write_text(suite)
                with patch.object(phases, 'run_pi', return_value='VERIFY_PASSED: looks fine'):
                    verdict = phases.verify(proj)
                self.assertEqual(verdict, 'VERIFY_FAILED')
                self.assertEqual((proj / 'verify_verdict.txt').read_text().strip(), verdict)

    def test_real_passing_suite_verifies_without_model_marker(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            (proj / 'test_math.py').write_text('def test_sum():\n    assert 1 + 2 == 3\n')
            with patch.object(phases, 'run_pi', return_value='No verdict available'):
                self.assertEqual(phases.verify(proj), 'VERIFY_PASSED')


class DiscardProductResidue(unittest.TestCase):
    def git(self, proj, *args):
        return subprocess.run(['git', '-C', str(proj), *args], check=True,
                              capture_output=True, text=True).stdout

    def test_discard_restores_head_and_index_but_preserves_bookkeeping(self):
        for staged in (False, True):
            with self.subTest(staged=staged), TemporaryDirectory() as directory:
                proj = Path(directory)
                self.git(proj, 'init')
                self.git(proj, 'config', 'user.name', 'Test')
                self.git(proj, 'config', 'user.email', 'test@example.invalid')
                (proj / '.gitignore').write_text(GITIGNORE)
                (proj / 'main.py').write_text('original = True\n')
                (proj / 'unchanged.py').write_text('unchanged = True\n')
                kb = Graph(proj / 'kb/graph.json')
                kb.node('decision', 'original')
                self.git(proj, 'add', '.')
                self.git(proj, 'commit', '-m', 'base')
                (proj / 'new_module.py').write_text('unfinished = True\n')
                if staged:
                    (proj / 'main.py').write_text('broken = True\n')
                    self.git(proj, 'add', '.')
                kb.node('blocker', 'Issue #2 blocked', 'Keep this evidence')
                expected_kb = (proj / 'kb/graph.json').read_bytes()
                (proj / 'issue_2_output.txt').write_text('worker evidence')
                phases._discard_residue(proj, 2, 'test')
                self.assertEqual((proj / 'main.py').read_text(), 'original = True\n')
                self.assertFalse((proj / 'new_module.py').exists())
                self.assertEqual(self.git(proj, 'diff', '--cached'), '')
                self.assertEqual((proj / 'kb/graph.json').read_bytes(), expected_kb)
                self.assertEqual((proj / 'issue_2_output.txt').read_text(), 'worker evidence')
                backup = next((proj / '.git/siesta-recovery').iterdir())
                with tarfile.open(backup / 'files.tar.gz') as archive:
                    self.assertNotIn('unchanged.py', archive.getnames())
                    if not staged:
                        self.assertEqual(archive.extractfile('new_module.py').read(),
                                         b'unfinished = True\n')
                if staged:
                    self.git(proj, 'apply', '--index', str(backup / 'staged.patch'))
                    self.assertEqual((proj / 'main.py').read_text(), 'broken = True\n')
                    self.assertEqual((proj / 'new_module.py').read_text(), 'unfinished = True\n')

    def test_second_failed_regression_repair_is_recovered_before_halt(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            self.git(proj, 'init')
            self.git(proj, 'config', 'user.name', 'Test')
            self.git(proj, 'config', 'user.email', 'test@example.invalid')
            (proj / '.gitignore').write_text(GITIGNORE)
            (proj / 'main.py').write_text('original = True\n')
            (proj / 'test_main.py').write_text('def test_broken():\n    assert False\n')
            (proj / 'issues.md').write_text(
                '## Issue #1: Base\nDone\n## Issue #2: Next\nNext\n## Issue #3: Last\nLast\n')
            kb = Graph(proj / 'kb/graph.json')
            kb.node('decision', 'Issue #1 completed', 'Existing committed base')
            self.git(proj, 'add', '.')
            self.git(proj, 'commit', '-m', 'base')
            attempts = []

            def failed_repair(*args, **kwargs):
                attempt = len(attempts) + 1
                attempts.append(attempt)
                (proj / 'main.py').write_text(f'failed_repair = {attempt}\n')
                (proj / 'staged_attempt.py').write_text(f'attempt = {attempt}\n')
                self.git(proj, 'add', 'staged_attempt.py')
                (proj / 'untracked_attempt.py').write_text(f'attempt = {attempt}\n')
                return 'REPAIR_DONE: attempted repair but regression still fails'

            with patch.object(phases, 'run_pi', side_effect=failed_repair), \
                 patch.object(phases, 'GLOBAL_KB', proj / 'kb/global.json'):
                with self.assertRaises(SystemExit) as raised:
                    phases.execute(proj, kb)
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(attempts, [1, 2])
            self.assertEqual(self.git(proj, 'show', 'HEAD:main.py'), 'original = True\n')
            tracked = self.git(proj, 'ls-tree', '--name-only', 'HEAD').splitlines()
            self.assertNotIn('staged_attempt.py', tracked)
            self.assertNotIn('untracked_attempt.py', tracked)
            self.assertFalse((proj / 'staged_attempt.py').exists())
            self.assertFalse((proj / 'untracked_attempt.py').exists())
            backups = sorted(path for path in (proj / '.git/siesta-recovery').iterdir()
                             if 'staged_attempt.py' in (path / 'staged.patch').read_text())
            self.assertEqual(len(backups), 2)
            self.assertIn('+failed_repair = 2', (backups[-1] / 'unstaged.patch').read_text())
            self.assertIn('+attempt = 2', (backups[-1] / 'staged.patch').read_text())
            with tarfile.open(backups[-1] / 'files.tar.gz') as archive:
                self.assertEqual(archive.extractfile('untracked_attempt.py').read(),
                                 b'attempt = 2\n')
            self.assertIn('Phase 3 halted: unrepairable suite',
                          [node['summary'] for node in kb.query(type_='blocker')])

    def test_untracked_only_is_dirty(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            self.git(proj, 'init')
            (proj / 'unfinished.py').write_text('broken = True\n')
            self.assertFalse(phases._tree_is_clean(proj))


class RealInterviewDeadline(unittest.TestCase):
    def test_deadline_covers_open_stdout_and_retains_partial_line(self):
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / 'interview.txt'
            command = [sys.executable, '-c',
                       "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(2)"]
            started = time.monotonic()
            with patch.object(pi, 'build_args', return_value=command), \
                 patch.object(pi, 'PI_TIMEOUT', 0.2):
                result = pi.run_pi('planner', '', '', interactive=True, artifact=artifact)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(result, 'partial')
            self.assertEqual(artifact.read_text(), 'partial')

    def test_failed_provider_marker_is_not_an_answer(self):
        command = [sys.executable, '-c',
                   "import sys; print('VERIFY_PASSED: partial'); sys.exit(1)"]
        with TemporaryDirectory() as directory, patch.object(pi, 'build_args', return_value=command):
            artifact = Path(directory) / 'output.txt'
            result = pi.run_pi('worker', '', '', artifact=artifact)
            self.assertEqual(result, '')
            self.assertIn('VERIFY_PASSED: partial', artifact.read_text())
