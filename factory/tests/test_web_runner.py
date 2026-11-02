"""Desktop process lifecycle, verdicts and file boundaries."""
import os
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from pipeline.web.runner import Desktop, Conflict
from pipeline import project_metadata


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.factory = Path(self.tmp.name) / 'factory'
        self.factory.mkdir()
        self.desktop = Desktop(self.factory)
        self.addCleanup(self.desktop.close)

    def launch(self, code, idea='test project'):
        return self.desktop.start(idea, auto=True, command=[sys.executable, '-u', '-c', code])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.desktop.snapshot()
            if predicate(state):
                return state
            time.sleep(.02)
        self.fail(f'Timed out: {state}')

    def test_interview_reply_and_duplicate_start_are_guarded(self):
        self.launch("from pipeline.events import update; update(phase='0', input_id='first'); "
                    "print('Your idea?'); answer=input(); print('ANSWER:'+answer); "
                    "update(input_id=None)")
        state = self.wait_for(lambda s: s.get('input_id') == 'first')
        with self.assertRaises(Conflict):
            self.launch('pass', idea='another project')
        with self.assertRaises(Conflict):
            self.desktop.reply(state['id'], 'stale', 'no')
        self.desktop.reply(state['id'], 'first', 'a timer')
        with self.assertRaises(Conflict):
            self.desktop.reply(state['id'], 'first', 'duplicate')
        final = self.wait_for(lambda s: s['status'] not in ('running', 'waiting'))
        self.assertIn('ANSWER:a timer', final['output'])
        self.assertEqual(final['status'], 'incomplete')

    def test_project_title_edit_and_soft_delete(self):
        project = self.factory / 'projects/tiny-app'
        project.mkdir(parents=True)
        (project / '.pipeline-idea').write_text('A tiny app')
        project_metadata.write_name(project, 'My first app')
        self.assertEqual(self.desktop.project('tiny-app')['display_name'], 'My first app')
        edited = self.desktop.rename_project('tiny-app', 'New title')
        self.assertEqual(edited['display_name'], 'New title')
        with self.assertRaises(Conflict):
            self.desktop.delete_project('tiny-app', 'wrong')
        self.desktop.delete_project('tiny-app', 'tiny-app')
        self.assertFalse(project.exists())
        self.assertEqual(self.desktop.projects(), [])
        self.assertEqual(len(list((self.factory / 'projects/.trash').iterdir())), 1)

    def test_new_project_name_does_not_resume_an_existing_idea(self):
        project = self.factory / 'projects/test-project'
        project.mkdir(parents=True)
        (project / '.pipeline-idea').write_text('test project')
        with self.assertRaises(Conflict):
            self.desktop.start('test project', display_name='Another title')

    def test_legacy_project_can_be_renamed_without_idea_sidecar(self):
        project = self.factory / 'projects/legacy-app'
        (project / '.git').mkdir(parents=True)
        (project / 'kb').mkdir()
        (project / 'kb/graph.json').write_text('{"nodes":[],"edges":[]}')
        self.assertEqual(self.desktop.rename_project('legacy-app', 'Legacy renamed')
                         ['display_name'], 'Legacy renamed')

    def test_stop_terminates_active_run_and_allows_another(self):
        run = self.launch('import time; time.sleep(30)')
        with self.assertRaises(Conflict):
            self.desktop.rename_project('test-project', 'Changed')
        with self.assertRaises(Conflict):
            self.desktop.delete_project('test-project', 'test-project')
        with self.assertRaises(Conflict):
            self.desktop.stop('wrong-id')
        stopped = self.desktop.stop(run['id'])
        self.assertEqual(stopped['status'], 'stopped')
        self.assertIsNotNone(stopped['returncode'])
        with self.assertRaises(Conflict):
            self.desktop.stop(run['id'])
        next_run = self.launch("print('next')", idea='another app')
        self.assertNotEqual(next_run['id'], run['id'])

    def test_model_selection_is_validated_and_forwarded_to_cli(self):
        config = self.factory / 'config'
        config.mkdir()
        source = Path(__file__).resolve().parents[1] / 'config/models.json'
        (config / 'models.json').write_text(source.read_text())
        process = Mock()
        process.pid = 0
        process.poll.return_value = None
        selection = {'phases': {'interview': {
            'model': 'local-interviewer', 'provider': 'ollama'}}}
        with patch('pipeline.web.runner.subprocess.Popen', return_value=process) as popen, \
             patch('pipeline.model_catalog.catalog', return_value={'models': [{
                 'id': 'local-interviewer', 'pi_registered': True,
                 'installed': True, 'preparation': None}]}):
            self.desktop.start('select a model', auto=True, model_selection=selection)
            process.poll.return_value = 0
            args = popen.call_args.args[0]
            path = Path(args[args.index('--model-selection') + 1])
            written = json.loads(path.read_text())
            self.assertEqual(written['phases'], selection['phases'])
            self.assertEqual(written['agents'], {})
            self.assertIn('--auto', args)

    def test_invalid_model_selection_is_rejected_before_start(self):
        config = self.factory / 'config'
        config.mkdir()
        source = Path(__file__).resolve().parents[1] / 'config/models.json'
        (config / 'models.json').write_text(source.read_text())
        with patch('pipeline.web.runner.subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'unknown phase'):
                self.desktop.start('reject bad model route', model_selection={
                    'phases': {'not-a-phase': {'model': 'x', 'provider': 'ollama'}}})
            popen.assert_not_called()

    def test_unprepared_model_is_rejected_before_launch(self):
        config = self.factory / 'config'
        config.mkdir()
        source = Path(__file__).resolve().parents[1] / 'config/models.json'
        (config / 'models.json').write_text(source.read_text())
        with patch('pipeline.model_catalog.catalog', return_value={'models': [{
                'id': 'unregistered', 'pi_registered': False, 'installed': True,
                'preparation': 'Register in Pi'}]}), \
             patch('pipeline.web.runner.subprocess.Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'needs Pi/Ollama preparation'):
                self.desktop.start('reject unprepared route', model_selection={
                    'phases': {'planning': {'model': 'unregistered', 'provider': 'ollama'}}})
            popen.assert_not_called()

    def test_review_policy_is_forwarded_and_status_has_unknown_usage(self):
        process = Mock()
        process.pid = 0
        process.poll.return_value = None
        with patch('pipeline.web.runner.subprocess.Popen', return_value=process) as popen:
            self.desktop.start('deep review', review_policy='deep')
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index('--review-policy') + 1], 'deep')
            state = self.desktop.snapshot()
            self.assertIsNone(state['tokens'])
            self.assertIsNone(state['cost'])
            process.poll.return_value = 0
        with self.assertRaisesRegex(ValueError, 'review policy'):
            self.desktop.start('bad policy', review_policy='unlimited')

    def test_success_requires_complete_checkpoint_and_verdict(self):
        project = self.factory / 'projects/test-project'
        project.mkdir(parents=True)
        (project / '.pipeline-checkpoint').write_text('complete')
        (project / 'verify_verdict.txt').write_text('VERIFY_PASSED')
        self.launch("print('done')")
        final = self.wait_for(lambda s: s['status'] != 'running')
        self.assertEqual(final['status'], 'complete')

    def test_nonzero_exit_vetoes_saved_success(self):
        project = self.factory / 'projects/test-project'
        project.mkdir(parents=True)
        (project / '.pipeline-checkpoint').write_text('complete')
        (project / 'verify_verdict.txt').write_text('VERIFY_PASSED')
        self.launch("import sys; print('provider failed'); sys.exit(3)")
        final = self.wait_for(lambda s: s['status'] != 'running')
        self.assertEqual(final['status'], 'failed')
        self.assertEqual(final['returncode'], 3)

    def test_project_documents_cannot_escape_allowlist_or_directory(self):
        project = self.factory / 'projects/example'
        project.mkdir(parents=True)
        (project / '.pipeline-idea').write_text('Example project')
        (project / 'spec.md').write_text('# A harmless specification')
        secret = Path(self.tmp.name) / 'private.txt'
        secret.write_text('do not expose')
        (project / 'issues.md').symlink_to(secret)
        self.assertEqual(self.desktop.document('example', 'spec.md'), '# A harmless specification')
        for name, artifact in [('../', 'spec.md'), ('example', '../private.txt'), ('example', 'issues.md')]:
            with self.subTest(name=name, artifact=artifact), self.assertRaises(ValueError):
                self.desktop.document(name, artifact)
        self.assertEqual(self.desktop.projects()[0]['idea'], 'Example project')

    def test_close_terminates_live_child_and_output_is_bounded(self):
        self.launch("import time; print('x'*100000); time.sleep(30)")
        self.wait_for(lambda s: 'x' in s['output'])
        process = self.desktop.process
        self.assertLessEqual(len(self.desktop.snapshot()['output']), 65536)
        self.desktop.close()
        self.assertIsNotNone(process.poll())

    def test_shutdown_unwinds_a_pi_call_and_kills_its_separate_group(self):
        config = self.factory / 'config'
        config.mkdir()
        (config / 'models.json').write_text(
            (Path(__file__).resolve().parents[1] / 'config/models.json').read_text())
        pid_file = self.factory / 'provider.pid'
        provider = f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); time.sleep(30)"
        self.launch("import sys; from pipeline.web import worker; from pipeline import pi; "
                    f"pi.build_args=lambda *a,**kw:[sys.executable,'-c',{provider!r}]; "
                    "worker.run=lambda:pi.run_pi('planner','body','user'); worker.main()")
        self.wait_for(lambda s: pid_file.exists() or s['status'] == 'failed')
        self.assertTrue(pid_file.exists(), self.desktop.snapshot()['output'])
        pid = int(pid_file.read_text())
        self.desktop.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_stop_unwinds_a_pi_call_and_kills_its_separate_group(self):
        config = self.factory / 'config'
        config.mkdir()
        (config / 'models.json').write_text(
            (Path(__file__).resolve().parents[1] / 'config/models.json').read_text())
        pid_file = self.factory / 'provider.pid'
        provider = f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); time.sleep(30)"
        run = self.launch("import sys; from pipeline.web import worker; from pipeline import pi; "
                          f"pi.build_args=lambda *a,**kw:[sys.executable,'-c',{provider!r}]; "
                          "worker.run=lambda:pi.run_pi('planner','body','user'); worker.main()")
        self.wait_for(lambda s: pid_file.exists() or s['status'] == 'failed')
        self.assertTrue(pid_file.exists(), self.desktop.snapshot()['output'])
        pid = int(pid_file.read_text())
        self.assertEqual(self.desktop.stop(run['id'])['status'], 'stopped')
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_second_desktop_cannot_write_the_same_factory(self):
        with self.assertRaises(Conflict):
            Desktop(self.factory)
        self.desktop.close()
        replacement = Desktop(self.factory)
        replacement.close()

    def test_reported_project_name_is_authoritative(self):
        project = self.factory / 'projects/project-actual'
        project.mkdir(parents=True)
        (project / '.pipeline-checkpoint').write_text('complete')
        (project / 'verify_verdict.txt').write_text('VERIFY_PASSED')
        self.launch("from pipeline.events import update; update(project='project-actual')", idea='🐍')
        state = self.wait_for(lambda s: s['status'] != 'running')
        self.assertEqual(state['project'], 'project-actual')
        self.assertEqual(state['status'], 'complete')


if __name__ == "__main__":
    unittest.main()
