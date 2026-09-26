"""Real reproductions of ignored prompt inputs and lingering Pi writers."""
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline import phases, pi, text
from pipeline.kb import Graph


class PromptInputs(unittest.TestCase):
    def test_ignored_files_vendor_trees_and_symlinks_stay_out_of_prompts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            proj = root / 'project'
            proj.mkdir()
            subprocess.run(['git', 'init', '-q', str(proj)], check=True)
            (proj / '.gitignore').write_text('private.json\n')
            for name, content in {
                'private.json': 'PRIVATE_SENTINEL', '.venv/library.py': 'VENDOR_SENTINEL',
                'node_modules/library.js': 'NODE_SENTINEL', '.env.json': 'ENV_SENTINEL',
                '.pi/settings.json': 'PROFILE_SENTINEL', 'new_module.py': 'PRODUCT_SENTINEL',
                'vendor/library.py': 'VENDORED_SENTINEL',
                '.env/secrets.json': 'ENV_DIR_SENTINEL',
            }.items():
                target = proj / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            (root / 'outside.json').write_text('OUTSIDE_SENTINEL')
            (proj / 'linked.json').symlink_to(root / 'outside.json')
            (proj / 'linked_dir').symlink_to(root, target_is_directory=True)
            subprocess.run(['git', '-C', str(proj), 'add', '-f', 'private.json'], check=True)
            gathered = phases.gather(proj)
            self.assertIn('PRODUCT_SENTINEL', gathered)
            for marker in ('PRIVATE', 'VENDOR', 'NODE', 'ENV', 'PROFILE', 'OUTSIDE',
                           'VENDORED', 'ENV_DIR'):
                self.assertNotIn(marker + '_SENTINEL', gathered)


    def test_git_failure_cannot_disable_ignore_filtering(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            subprocess.run(['git', 'init', '-q', str(proj)], check=True)
            (proj / '.gitignore').write_text('private.json\n')
            (proj / 'private.json').write_text('PRIVATE_SENTINEL')
            (proj / '.git' / 'config').write_text('[broken\n')
            with self.assertRaisesRegex(RuntimeError, 'ignored'):
                phases.gather(proj)

    def test_empty_git_tree_has_no_context(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            subprocess.run(['git', 'init', '-q', str(proj)], check=True)
            self.assertEqual(phases.gather(proj), '')

    def test_plain_directory_keeps_product_files(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            (proj / 'new_module.py').write_text('PRODUCT_SENTINEL')
            self.assertIn('PRODUCT_SENTINEL', phases.gather(proj))


class ProcessLifetime(unittest.TestCase):
    def test_timeout_kills_descendant_and_retains_partial_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            late = root / 'late.txt'
            artifact = root / 'output.txt'
            script = root / 'pi.py'
            script.write_text(
                'import subprocess,sys,time\n'
                'subprocess.Popen([sys.executable, "-c", '
                '"import pathlib,sys,time; time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text(\'late\')", '
                f'{str(late)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                'print("partial stdout", flush=True)\n'
                'print("partial stderr", file=sys.stderr, flush=True)\n'
                'time.sleep(2)\n')
            with patch.object(pi, 'build_args', return_value=[sys.executable, str(script)]), \
                 patch.object(pi, 'PI_TIMEOUT', 0.2):
                self.assertEqual(pi.run_pi('worker', '', '', artifact=artifact), '')
            # Give a surviving child time to perform its forbidden write.
            time.sleep(0.6)
            self.assertFalse(late.exists(), 'A child continued writing after the timeout')
            self.assertIn('partial stdout', artifact.read_text())
            self.assertIn('partial stderr', artifact.read_text())

    def test_failed_interactive_answer_is_evidence_not_an_intent(self):
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / 'interview.txt'
            command = [sys.executable, '-c',
                       "import sys; print('INTENT_FINALIZED: untrusted partial intent'); sys.exit(1)"]
            with patch.object(pi, 'build_args', return_value=command):
                self.assertEqual(pi.run_pi('planner', '', '', interactive=True, artifact=artifact), '')
            self.assertIn('untrusted partial intent', artifact.read_text())
            self.assertIsNone(text.INTENT.search(artifact.read_text()))


    def test_interactive_timeout_kills_child_holding_output_pipes(self):
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / 'interview.txt'
            command = [sys.executable, '-c',
                       'import subprocess,sys; '
                       'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"]); '
                       'print("INTENT_FINALIZED: partial", flush=True); '
                       'print("provider partial", file=sys.stderr, flush=True)']
            started = time.monotonic()
            with patch.object(pi, 'build_args', return_value=command), \
                 patch.object(pi, 'PI_TIMEOUT', 0.2):
                self.assertEqual(pi.run_pi('planner', '', '', interactive=True,
                                          artifact=artifact), '')
            self.assertLess(time.monotonic() - started, 2)
            self.assertIn('provider partial', artifact.read_text())
            self.assertIn('INTENT_FINALIZED: partial', artifact.read_text())
            self.assertIsNone(text.INTENT.search(artifact.read_text()))

    def test_interactive_success_cleans_up_child_holding_only_stderr(self):
        command = [sys.executable, '-c',
                   'import subprocess,sys; '
                   'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"], '
                   'stdout=subprocess.DEVNULL); '
                   'print("INTENT_FINALIZED: complete", flush=True)']
        started = time.monotonic()
        with patch.object(pi, 'build_args', return_value=command), \
             patch.object(pi, 'PI_TIMEOUT', 0.2):
            answer = pi.run_pi('planner', '', '', interactive=True)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(answer, 'INTENT_FINALIZED: complete\n')

    def test_stderr_intent_is_not_usable_when_reading_saved_artifact(self):
        with TemporaryDirectory() as directory:
            artifact = Path(directory) / 'interview.txt'
            command = [sys.executable, '-c',
                       'import sys; print("Question?"); '
                       'print("provider log\\nINTENT_FINALIZED: stderr", file=sys.stderr)']
            with patch.object(pi, 'build_args', return_value=command):
                answer = pi.run_pi('planner', '', '', interactive=True, artifact=artifact)
            self.assertEqual(answer, 'Question?\n')
            self.assertIsNone(text.INTENT.search(artifact.read_text()))

    def test_successful_closeout_preserves_failed_interview_evidence(self):
        with TemporaryDirectory() as directory:
            proj = Path(directory)
            kb = Graph(proj / 'kb' / 'graph.json')
            commands = [
                [sys.executable, '-c', 'import sys; '
                 'print("INTENT_FINALIZED: partial"); '
                 'print("failure details", file=sys.stderr); sys.exit(1)'],
                [sys.executable, '-c', 'print("INTENT_FINALIZED: complete intent")'],
            ]
            with patch.object(pi, 'build_args', side_effect=commands), \
                 patch.object(phases, '_commit'):
                intent, _ = phases.phase0(proj, 'test', 'original idea', False, kb)
            self.assertEqual(intent, 'complete intent')
            evidence = (proj / 'interview_failed_output.txt').read_text()
            self.assertIn('INTENT_FINALIZED: partial', evidence)
            self.assertIn('failure details', evidence)
            self.assertIsNone(text.INTENT.search(evidence))


if __name__ == '__main__':
    unittest.main()
