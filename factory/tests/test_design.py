"""Independent review gates reject unsupported claims before delivery."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import design, model_selection, pi, repository


SPEC = '# Timer\n\n## Acceptance criteria\n- R1: Print elapsed seconds.\n'
PASS = json.dumps({'verdict': 'passed', 'findings': []})


class DesignGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.proj)], check=True)
        (self.proj / 'spec.md').write_text(SPEC)
        (self.proj / 'issues.md').write_text(
            '## Issue #1: Timer\nR1: Print elapsed seconds.\n'
            'Test strategy: Assert the printed value.\nDependencies: none.\n')
        subprocess.run(['git', '-C', str(self.proj), 'config', 'user.name', 'Design Test'],
                       check=True)
        subprocess.run(['git', '-C', str(self.proj), 'config', 'user.email',
                        'design@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(self.proj), 'add', 'spec.md', 'issues.md'],
                       check=True)
        subprocess.run(['git', '-C', str(self.proj), 'commit', '-qm', 'Initial design'],
                       check=True)

    def test_two_isolated_reviews_are_cached_only_for_the_same_design(self):
        with patch.object(design, 'run_pi', return_value=PASS) as run:
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 3)
            for call in run.call_args_list:
                self.assertTrue(call.kwargs['isolated'])
                self.assertEqual(call.kwargs['tools'], 'no')
                self.assertIn(call.kwargs['agent'], {
                    'design-comprehension-reviewer', 'design-simplicity-reviewer',
                    'design-readiness-reviewer'})
                self.assertNotIn('KB', call.args[1])
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 3)
            (self.proj / 'issues.md').write_text(
                '## Issue #1: Timer\nR1: Print milliseconds.\n'
                'Test strategy: Assert the printed value.\nDependencies: none.\n')
            design.review(self.proj, 'A timer')
            self.assertEqual(run.call_count, 6)

    def test_design_approval_is_bound_to_specialist_model_routes(self):
        with patch.object(design, 'run_pi', return_value=PASS) as run:
            design.review(self.proj, 'A timer')
            selection = model_selection.normalize_selection({
                'agents': {'design_review': {
                    'design-comprehension-reviewer': {
                        'model': 'comprehension-v2', 'provider': 'ollama'}}}},
                role_defaults=design.ROLE)
            model_selection.save_project(self.proj, selection)
            design.review(self.proj, 'A timer')
        self.assertEqual(run.call_count, 6)

    def test_symlinked_evidence_directory_is_rejected_before_writing(self):
        target = self.proj / 'outside-evidence'
        target.mkdir()
        (self.proj / '.siesta').symlink_to(target, target_is_directory=True)
        with patch.object(design, 'run_pi') as run:
            with self.assertRaisesRegex(RuntimeError, 'evidence directory.*symlink'):
                design.review(self.proj, 'A timer')
        run.assert_not_called()
        self.assertFalse((target / '.gitignore').exists())

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

    def test_design_review_requires_extended_mode_for_sensitive_issue_types(self):
        (self.proj / 'issues.md').write_text(
            '## Issue #1: Add login\nR1: Print elapsed seconds.\n'
            'Test strategy: Assert output.\nDependencies: none.\n'
            'Add authentication and a regression test.\n')
        with patch.object(design, 'run_pi') as run:
            with self.assertRaisesRegex(ValueError, 'Review: extended'):
                design.review(self.proj, 'A timer with accounts')
            run.assert_not_called()

        (self.proj / 'issues.md').write_text(
            '## Issue #1: Add login\nReview: extended\n'
            'R1: Print elapsed seconds.\nTest strategy: Assert output.\n'
            'Dependencies: none.\n'
            'Add authentication and a regression test.\n')
        with patch.object(design, 'run_pi', return_value=PASS) as run:
            design.review(self.proj, 'A timer with accounts')
        self.assertEqual(run.call_count, 3)

    def test_plan_coverage_requires_each_requirement_and_test_strategy(self):
        good = ('## Issue #1: Timer\nR1: Print elapsed seconds.\n'
                'Test strategy: Capture stdout and compare the value.\n'
                'Dependencies: none.\n')
        design.validate_plan_coverage(SPEC, good)
        for plan in (
                '## Issue #1: Timer\nTest strategy: Assert output.\n'
                'Dependencies: none.\n',
                '## Issue #1: Timer\nR1: Print elapsed seconds.\n'
                'Dependencies: none.\n',
                '## Issue #1: Timer\nR1: Print elapsed seconds.\n'
                'Test strategy: \nDependencies: none.\n'):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                design.validate_plan_coverage(SPEC, plan)

    def test_markdown_bold_issue_labels_keep_their_protocol_meaning(self):
        plan = ('## Issue #1: Public timer API\n'
                'R1: Print elapsed seconds.\n'
                '**Test strategy:** Run the CLI and assert exact stdout.\n'
                '**Dependencies:** none.\n'
                '**Review: extended**\n'
                'Expose a public interface.\n')
        issues = design.validate_plan_coverage(SPEC, plan)
        self.assertEqual(list(issues), [1])
        self.assertEqual(repository.issue_review_level(issues[1]), 'extended')

    def test_plan_rejects_self_forward_and_missing_dependencies(self):
        cases = (
            '## Issue #1: First\nR1\nTest strategy: assert output\nDependencies: #1\n',
            '## Issue #1: First\nR1\nTest strategy: assert output\nDependencies: #2\n',
            '## Issue #1: First\nR1\nTest strategy: assert output\n'
            '## Issue #2: Second\nTest strategy: assert output\nDependencies: #9\n',
            '## Issue #2: Second\nR1\nTest strategy: assert output\nDependencies: #1\n'
            '## Issue #1: First\nTest strategy: assert output\nDependencies: none\n',
        )
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaisesRegex(ValueError, 'depend'):
                design.validate_plan_coverage(SPEC, plan)

    def test_design_repair_is_validated_committed_then_reviewed_again(self):
        initial_spec = (self.proj / 'spec.md').read_text()
        initial_plan = (self.proj / 'issues.md').read_text()
        repaired_plan = (initial_plan + '\n## Issue #2: Test output\n'
                         'R1: Print elapsed seconds.\n'
                         'Test strategy: Capture and compare stdout.\n'
                         'Dependencies: #1.\n')
        calls = []

        def fake_pi(role, body, user, **kwargs):
            calls.append((role, body, user, kwargs))
            if kwargs.get('agent') == 'planner':
                return json.dumps({'version': 1, 'summary': 'Map R1 to output tests.',
                                   'spec': initial_spec, 'plan': repaired_plan})
            if len([call for call in calls if call[3].get('agent') ==
                    'design-comprehension-reviewer']) == 1:
                return json.dumps({'verdict': 'failed',
                                   'findings': ['R1 needs a verifiable output test.']})
            return PASS

        with patch.object(design, 'run_pi', side_effect=fake_pi), \
                patch.object(design.repository, 'commit', return_value='repair-commit') as commit:
            design.review(self.proj, 'A timer')

        self.assertEqual(len(calls), 7)
        self.assertEqual(calls[3][3]['agent'], 'planner')
        self.assertEqual(calls[3][3]['context_kind'], 'design_repair')
        self.assertTrue(calls[3][3]['isolated'])
        self.assertIn('Test output', calls[4][1])
        commit.assert_called_once_with(self.proj, 'Design documents repaired before implementation')
        self.assertEqual((self.proj / 'issues.md').read_text(), repaired_plan)
        ledger = json.loads((self.proj / '.siesta/design-review.json').read_text())
        self.assertEqual(ledger['status'], 'approved')
        self.assertEqual(len(ledger['repairs']), 1)
        self.assertEqual(ledger['repairs'][0]['commit'], 'repair-commit')

    def test_invalid_scope_repair_is_not_written_or_committed(self):
        initial_spec = (self.proj / 'spec.md').read_text()
        initial_plan = (self.proj / 'issues.md').read_text()
        changed_spec = initial_spec.replace('Print elapsed seconds.',
                                            'Upload user data to a hosted service.')

        def fake_pi(role, body, user, **kwargs):
            if kwargs.get('agent') == 'planner':
                return json.dumps({'version': 1, 'summary': 'Expand scope.',
                                   'spec': changed_spec, 'plan': initial_plan})
            return json.dumps({'verdict': 'failed',
                               'findings': ['The plan needs a concrete test strategy.']})

        with patch.object(design, 'run_pi', side_effect=fake_pi), \
                patch.object(design.repository, 'commit') as commit:
            with self.assertRaisesRegex(RuntimeError, 'criteria|scope'):
                design.review(self.proj, 'A timer')
        self.assertEqual((self.proj / 'spec.md').read_text(), initial_spec)
        self.assertEqual((self.proj / 'issues.md').read_text(), initial_plan)
        commit.assert_not_called()

    def test_design_repair_budget_is_bounded(self):
        initial_spec = (self.proj / 'spec.md').read_text()
        initial_plan = (self.proj / 'issues.md').read_text()
        calls = []

        def fake_pi(role, body, user, **kwargs):
            agent = kwargs.get('agent')
            calls.append(agent)
            if agent == 'planner':
                return json.dumps({'version': 1, 'summary': 'No document change.',
                                   'spec': initial_spec, 'plan': initial_plan})
            return json.dumps({'verdict': 'failed',
                               'findings': ['Coverage remains unclear.']})

        with patch.object(design, 'run_pi', side_effect=fake_pi), \
                patch.object(design.repository, 'commit', return_value='repair'):
            with self.assertRaisesRegex(RuntimeError, 'repair limit'):
                design.review(self.proj, 'A timer')
        ledger = json.loads((self.proj / '.siesta/design-review.json').read_text())
        self.assertEqual(ledger['status'], 'blocked')
        self.assertEqual(len(ledger['repairs']), 2)
        self.assertEqual(calls.count('planner'), 2)
        before_resume = len(calls)
        with patch.object(design, 'run_pi', side_effect=fake_pi):
            with self.assertRaisesRegex(RuntimeError, 'remains blocked'):
                design.review(self.proj, 'A timer')
        self.assertEqual(len(calls), before_resume)

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
