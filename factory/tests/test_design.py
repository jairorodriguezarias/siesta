"""Independent review gates reject unsupported claims before delivery."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import design, pi, repository


SPEC = '# Timer\n\n## Acceptance criteria\n- R1: Print elapsed seconds.\n'
PASS = json.dumps({'verdict': 'passed', 'findings': []})


class DesignGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.proj)], check=True)
        (self.proj / 'spec.md').write_text(SPEC)
        (self.proj / 'issues.md').write_text('## Issue #1: Timer\nPrint seconds and test it.\n')

    def test_two_isolated_reviews_are_cached_only_for_the_same_design(self):
        with patch.object(design, 'run_pi', return_value=PASS) as run:
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertTrue(call.kwargs['isolated'])
                self.assertEqual(call.kwargs['tools'], 'no')
                self.assertNotIn('KB', call.args[1])
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 2)
            (self.proj / 'issues.md').write_text('## Issue #1: Timer\nPrint milliseconds.\n')
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 4)

    def test_rejection_and_malformed_answers_cannot_approve(self):
        for answer in ('', 'DESIGN_PASSED: trust me',
                       '{"verdict":"failed","findings":["No test plan"]}',
                       '{"verdict":"passed","findings":["Missing behavior"]}'):
            with self.subTest(answer=answer), patch.object(design, 'run_pi', return_value=answer):
                with self.assertRaisesRegex(RuntimeError, 'Design review'):
                    design.review(self.proj, 'A timer')
                self.assertFalse(repository.load_state(self.proj).get('design'))
                self.assertTrue((self.proj / '.siesta/design-review.md').exists())

    def test_requirements_are_stable_and_duplicates_or_absence_fail(self):
        self.assertEqual(design.requirements(SPEC), {'R1': 'Print elapsed seconds.'})
        self.assertEqual(design.requirements('## Success criteria\n- Print seconds.\n'),
                         {'R1': 'Print seconds.'})
        for spec in ('# Timer', SPEC + '- R1: Another requirement.\n',
                     '# Timer\n```\n- R1: Example only\n```'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                design.requirements(spec)

    def test_isolation_disables_inherited_context_and_discovery(self):
        args = pi.build_args('consultant', 'spec', 'review', tools='no', isolated=True)
        for flag in ('--no-session', '--no-context-files', '--no-extensions',
                     '--no-skills', '--no-prompt-templates', '--no-tools'):
            self.assertIn(flag, args)


class RequirementEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        (self.proj / 'spec.md').write_text(SPEC)
        (self.proj / 'timer.py').write_text('print(1)\n')
        (self.proj / 'test_timer.py').write_text('def test_seconds():\n    assert True\n')
        (self.proj / '.siesta').mkdir()
        (self.proj / '.siesta/tests.json').write_text(json.dumps({
            'passed': ['test_timer.py::test_seconds'], 'status': 'passed'}))
        self.report = {'requirements': [{'id': 'R1', 'status': 'supported',
            'tests': ['test_timer.py::test_seconds'], 'sources': ['timer.py'],
            'reason': 'The timer prints seconds and its test checks output.'}], 'drift': []}

    def audit(self, mechanical=True):
        with patch.object(design, 'run_pi', return_value=json.dumps(self.report)):
            return design.verify(self.proj, 'timer source', mechanical)

    def test_every_requirement_needs_real_passing_test_and_source_references(self):
        self.assertTrue(self.audit())
        self.report['requirements'][0]['tests'] = ['test_timer.py::test_invented']
        self.assertFalse(self.audit())
        saved = json.loads((self.proj / '.siesta/requirements.json').read_text())
        self.assertFalse(saved['passed'])

    def test_missing_duplicate_unsafe_and_contradicted_evidence_fails(self):
        valid = self.report['requirements'][0]
        cases = [[], [valid, valid], [{**valid, 'sources': ['../secret']}],
                 [{**valid, 'status': 'missing'}], [{**valid, 'tests': []}]]
        for rows in cases:
            with self.subTest(rows=rows):
                self.report['requirements'] = rows
                self.assertFalse(self.audit())

    def test_drift_and_failed_mechanical_checks_veto_support(self):
        self.report['drift'] = ['README promises milliseconds instead of seconds.']
        self.assertFalse(self.audit())
        self.report['drift'] = []
        self.assertFalse(self.audit(mechanical=False))

    def test_missing_or_malformed_reply_creates_a_failed_report(self):
        with patch.object(design, 'run_pi', return_value='No evidence available'):
            self.assertFalse(design.verify(self.proj, 'source', True))
        self.assertIn('FAIL', (self.proj / '.siesta/requirements.md').read_text())
