"""Skills must reach text-only roles without asking the model to read files."""
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from pipeline import phases, pi
from pipeline.kb import Graph
from pipeline.pi import build_args


class SkillContext(unittest.TestCase):
    def test_large_skill_context_reaches_child_without_os_argument_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'fake-pi'
            executable.write_text('#!/usr/bin/env python3\nimport sys\n'
                                  'prompt = sys.stdin.read() or sys.argv[-1]\n'
                                  'print(prompt, end="")\n')
            executable.chmod(0o755)
            body = 'Contexto ñ: ' * 16000
            with patch.object(pi, 'PI_BIN', str(executable)):
                output = pi.run_pi('consultant', body, 'Return the decision', tools='no')
        self.assertTrue(output.endswith(body + '\n\nReturn the decision'))
        self.assertIn('Agent identity: consultant', output)

    def test_text_only_role_receives_full_skills_before_its_task(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / 'advice'
            skill.mkdir()
            content = '---\nname: advice\ndescription: Advise.\n---\nKEEP_THIS_CONSTRAINT\n'
            (skill / 'SKILL.md').write_text(content)
            args = build_args('consultant', 'Task evidence', 'Return the decision',
                              skills=(skill,), tools='no')
            self.assertIn('--no-tools', args)
            self.assertIn(content, args[-1])
            self.assertTrue(args[-1].endswith('Task evidence\n\nReturn the decision'))

    def test_unreadable_required_skill_fails_before_calling_pi(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'missing'
            with self.assertRaises(FileNotFoundError):
                build_args('planner', 'Task', 'Return document',
                           skills=(missing,), tools='no')

    def test_worker_keeps_progressive_skill_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / 'coding'
            skill.mkdir()
            (skill / 'SKILL.md').write_text('WORKER_SKILL_DETAIL')
            args = build_args('worker', 'Code context', 'Implement', skills=(skill,))
            self.assertIn('--skill', args)
            self.assertNotIn('WORKER_SKILL_DETAIL', args[-1])

    def test_isolated_review_cannot_receive_skills(self):
        with self.assertRaises(ValueError):
            build_args('consultant', 'Design', 'Return JSON',
                       skills=(Path('untrusted'),), tools='no', isolated=True)

    def test_review_proxy_receives_intent_specification_and_decision_details(self):
        with tempfile.TemporaryDirectory() as directory:
            proj = Path(directory)
            (proj / 'spec.md').write_text('# Spec\n- R1: Keep all data on this machine.\n')
            (proj / 'issues.md').write_text('## Issue #1: Store notes\nImplement storage.\n')
            kb = Graph(proj / 'kb/graph.json')
            kb.node('intent', 'Human intent', 'Private notes must never leave this machine.')
            kb.node('decision', 'Storage choice', 'Use SQLite without network sync.')
            with patch.object(phases, 'run_pi', side_effect=[
                    'REVIEW_PASSED: storage is correct', 'APPROVED: within scope']) as call:
                phases.review(proj, kb)
            body = call.call_args.args[1]
            self.assertIn('Private notes must never leave this machine.', body)
            self.assertIn('- R1: Keep all data on this machine.', body)
            self.assertIn('Use SQLite without network sync.', body)

    def test_repair_cannot_succeed_with_an_unresolved_approval_request(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(phases, 'run_pi', return_value='PROXY_REQUEST: change the contract'), \
                    patch.object(phases, 'run_regression', return_value='passed'):
                self.assertFalse(phases._repair_regression(Path(directory), 1, 'Issue', 'Source'))

    def test_issue_proxy_uses_decision_details_even_when_summaries_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            proj = Path(directory)
            (proj / 'spec.md').write_text('# Spec\n- R1: Export locally.\n')
            kb = Graph(proj / 'kb/graph.json')
            kb.node('intent', 'Human intent', 'Export private notes as a local CSV.')
            kb.node('decision', 'Destination', 'Never upload notes to a hosted service.')
            with patch.object(phases, 'run_pi', return_value='APPROVED: local CSV is in scope') as call, \
                    patch.object(phases, '_worker', return_value=(
                        'Implemented local CSV export and ran its regression tests successfully.')):
                blocked, _ = phases._escalate(proj, 1, 'PROXY_REQUEST: export local CSV?',
                                              'Write the exporter', '[]', '', kb, {}, {}, [])
            self.assertFalse(blocked)
            body = call.call_args.args[1]
            for evidence in ('Export private notes as a local CSV.', '- R1: Export locally.',
                             'Never upload notes to a hosted service.', 'Write the exporter'):
                self.assertIn(evidence, body)

    def test_review_fix_handoff_blocks_before_committing(self):
        with tempfile.TemporaryDirectory() as directory:
            proj = Path(directory)
            (proj / 'spec.md').write_text('# Spec\n- R1: Preserve input.\n')
            (proj / 'issues.md').write_text('## Issue #1: Preserve input\nImplement.\n')
            kb = Graph(proj / 'kb/graph.json')
            with patch.object(phases, 'run_pi', side_effect=[
                    'REVIEW_FAILED: input is discarded', 'CONSULT: need a missing requirement']), \
                    patch.object(phases, '_discard_residue') as recover, \
                    patch.object(phases, '_commit') as commit:
                with self.assertRaisesRegex(RuntimeError, 'blocked awaiting'):
                    phases.review(proj, kb)
            recover.assert_called_once()
            commit.assert_not_called()

    def test_consultation_and_diagnosis_keep_fenced_error_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            proj = Path(directory)
            kb = Graph(proj / 'kb/graph.json')
            request = ('```text\nCONSULT: quoted example\n```\n'
                       'CONSULT: why does this assertion fail?\nCONTEXT: observed failure\n'
                       'CODE:\n```python\nassert actual == 42\n```')
            history = {}
            with patch.object(phases, 'run_pi', return_value='RESOLUTION: check the input') as call, \
                    patch.object(phases, '_worker', return_value=(
                        'Implemented the correction and ran the regression tests successfully.')):
                phases._escalate(proj, 1, request, 'Issue', '[]', '', kb, {}, history, [])
            self.assertIn('assert actual == 42', call.call_args.args[1])
            self.assertIn('```python', call.call_args.args[1])
            self.assertNotIn('quoted example', call.call_args.args[1])
            self.assertIn('assert actual == 42', history[1])
