"""Existing repositories can be extended without losing history or human work."""
import json

import subprocess
import sys
import unittest


import test_recovery_gates as fixtures


class IterationRuns(unittest.TestCase):
    setUp = fixtures.RecoveryGates.setUp
    git = fixtures.RecoveryGates.git
    seed = fixtures.RecoveryGates.seed
    calls = fixtures.RecoveryGates.calls
    summaries = fixtures.RecoveryGates.summaries

    def prepare(self):
        self.seed()
        stub = fixtures.FAKE_PI.replace(
            'answer("unexpected_planner", "Unexpected planner invocation during resume")',
            '''if "ITERATION_SPEC" in prompt:
        answer("iteration_spec", "# Double answer specification\\nAdd double_answer() returning twice answer(), with tests.")
    answer("iteration_plan", "## Issue #2: Double answer\\nAdd double_answer returning 84 and test it.")''')
        stub = stub.replace(
            'implement()\nanswer("execute",',
            '''if "Double answer" in prompt.rsplit("\\n\\n", 1)[-1]:
    if scenario == "block_iteration":
        Path("unfinished.py").write_text("unfinished = True\\n")
        answer("execute2", "")
    with Path("answer.py").open("a") as stream:
        stream.write("\\ndef double_answer():\\n    return answer() * 2\\n")
    Path("tests/test_double.py").write_text(
        "from answer import double_answer\\ndef test_double():\\n    assert double_answer() == 84\\n")
    answer("execute2", "ISSUE_OK: implemented double_answer and its regression test.")
implement()
answer("execute",''')
        (self.root / 'bin/pi').write_text(f'#!{sys.executable}\n' + stub)
        result = self.run_cli('--auto', self.idea)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.original_head = self.git('rev-parse', 'HEAD').strip()
        self.calls_file.write_text('')

    def run_cli(self, *args, scenario='ok'):
        return subprocess.run([sys.executable, '-m', 'pipeline', *map(str, args)],
                              cwd=self.root, env=self.env | {'RECOVERY_SCENARIO': scenario},
                              capture_output=True, text=True, timeout=60)

    def test_iteration_preserves_old_behavior_and_repeated_request_does_nothing(self):
        self.prepare()
        old_plan = (self.proj / 'issues.md').read_text()
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.proj / 'issues.md').read_text().startswith(old_plan.rstrip()))
        self.assertIn('return 42', self.git('show', 'HEAD:answer.py'))
        self.assertIn('def double_answer', self.git('show', 'HEAD:answer.py'))
        self.git('merge-base', '--is-ancestor', self.original_head, 'HEAD')
        self.assertEqual(self.summaries('decision').count('Issue #1 completed'), 1)
        self.assertEqual(self.summaries('decision').count('Issue #2 completed'), 1)
        head = self.git('rev-parse', 'HEAD')
        calls = self.calls_file.read_bytes()
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.calls_file.read_bytes(), calls)

    def test_blocked_iteration_resumes_without_replanning(self):
        self.prepare()
        blocked = self.run_cli('--project', self.proj, '--iterate', 'Double answer',
                               scenario='block_iteration')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertNotIn('Issue #2 completed', self.summaries('decision'))
        self.assertFalse((self.proj / 'unfinished.py').exists())
        old_plan = (self.proj / 'issues.md').read_bytes()
        different = self.run_cli('--project', self.proj, '--iterate', 'Something else')
        self.assertNotEqual(different.returncode, 0)
        self.assertEqual((self.proj / 'issues.md').read_bytes(), old_plan)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls('iteration_plan')), 1)
        self.assertEqual(self.summaries('decision').count('Issue #2 completed'), 1)

    def test_committed_regression_requires_fresh_verification(self):
        self.prepare()
        (self.proj / 'answer.py').write_text('def answer():\n    return 0\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'External regression')
        result = self.run_cli('--project', self.proj, '--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.calls('review'))
        self.assertTrue(self.calls('verify'))
        self.assertEqual((self.proj / 'verify_verdict.txt').read_text().strip(), 'VERIFY_FAILED')
        self.assertNotEqual((self.proj / '.pipeline-checkpoint').read_text().strip(), 'complete')

    def test_dirty_startup_preserves_every_file_and_kb_then_can_adopt(self):
        self.prepare()
        note = self.proj / 'human notes.txt'
        note.write_text('Keep my changes')
        kb_before = (self.proj / 'kb/graph.json').read_bytes()
        result = self.run_cli('--project', self.proj, '--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--adopt-changes', result.stderr)
        self.assertEqual(note.read_text(), 'Keep my changes')
        self.assertEqual((self.proj / 'kb/graph.json').read_bytes(), kb_before)
        self.assertEqual(self.calls_file.read_bytes(), b'')
        result = self.run_cli('--project', self.proj, '--adopt-changes', '--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('show', 'HEAD:human notes.txt'), 'Keep my changes')
        self.assertTrue(self.calls('verify'))

    def test_failed_plan_commit_preserves_previous_plan_and_stops_worker(self):
        self.prepare()
        old_plan = (self.proj / 'issues.md').read_bytes()
        hook = self.proj / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj / 'issues.md').read_bytes(), old_plan)
        self.assertFalse(self.calls('execute2'))
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.original_head)
        hook.unlink()
        recovered = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertEqual(recovered.returncode, 0, recovered.stderr)

    def test_invalid_target_and_colliding_idea_never_change_kb(self):
        self.prepare()
        kb_before = (self.proj / 'kb/graph.json').read_bytes()
        for target in (self.proj / 'tests', self.root / 'missing', self.factory):
            with self.subTest(target=target):
                result = self.run_cli('--project', target, '--resume')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.proj / 'kb/graph.json').read_bytes(), kb_before)
        collision = 'recovery answer cli DIFFERENT'
        from pipeline.__main__ import slug
        other = self.factory / 'projects' / slug(collision)
        other.symlink_to(self.proj, target_is_directory=True)
        result = self.run_cli('--auto', collision)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj / 'kb/graph.json').read_bytes(), kb_before)

    def test_completed_issue_rewrite_is_rejected_before_adoption(self):
        self.prepare()
        (self.proj / 'issues.md').write_text('## Issue #1: Revised\nReturn 99.\n')
        result = self.run_cli('--project', self.proj, '--adopt-changes', '--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('completed issue #1', result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.original_head)
        self.assertFalse(self.calls('execute'))

    def test_legacy_verification_without_fingerprint_is_checked_again(self):
        self.prepare()
        (self.proj / '.git/siesta-state.json').unlink()
        result = self.run_cli('--project', self.proj, '--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls('review'))
        self.assertTrue(self.calls('verify'))


    def test_missing_checkpoint_cannot_regenerate_an_existing_project(self):
        self.prepare()
        (self.proj / '.pipeline-checkpoint').unlink()
        before = (self.proj / 'issues.md').read_bytes()
        result = self.run_cli('--auto', '--project', self.proj, '--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checkpoint', result.stderr)
        self.assertEqual((self.proj / 'issues.md').read_bytes(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.original_head)
        self.assertEqual(self.calls_file.read_bytes(), b'')

    def test_worker_cannot_rewrite_completed_issue_during_iteration(self):
        self.prepare()
        before = (self.proj / 'issues.md').read_text()
        stub = self.root / 'bin/pi'
        code = stub.read_text().replace(
            'with Path("answer.py").open("a") as stream:',
            'Path("issues.md").write_text(Path("issues.md").read_text().replace("Return 42", "Return 99"))\n'
            '    with Path("answer.py").open("a") as stream:')
        stub.write_text(code)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Issue #2 completed', self.summaries('decision'))
        self.assertTrue((self.proj / 'issues.md').read_text().startswith(before.rstrip()))

    def test_deleted_live_completion_record_blocks_startup_without_mutation(self):
        self.prepare()
        graph = self.proj / 'kb/graph.json'
        data = json.loads(graph.read_text())
        data['nodes'] = [n for n in data['nodes'] if n['summary'] != 'Issue #1 completed']
        graph.write_text(json.dumps(data))
        before = graph.read_bytes()
        result = self.run_cli('--project', self.proj, '--resume')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('completion ledger', result.stderr)
        self.assertEqual(graph.read_bytes(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.original_head)

    def test_rejected_completion_commit_cannot_mark_project_complete(self):
        self.prepare()
        hook = self.proj / '.git/hooks/commit-msg'
        hook.write_text('#!/bin/sh\ncase "$(cat "$1")" in "Project verified:"*) exit 1;; esac\n')
        hook.chmod(0o755)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.summaries('decision').count('Project complete: recovery-answer-cli'), 1)
        self.assertNotEqual((self.proj / '.pipeline-checkpoint').read_text().strip(), 'complete')
        hook.unlink()
        result = self.run_cli('--project', self.proj, '--resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.summaries('decision').count('Issue #2 completed'), 1)

    def test_commit_hook_cannot_change_the_verified_product_and_report_success(self):
        self.prepare()
        hook = self.proj / '.git/hooks/commit-msg'
        hook.write_text(
            '#!/bin/sh\ncase "$(cat "$1")" in "Project verified:"*)\n'
            "printf 'def answer():\\n    return 0\\ndef double_answer():\\n    return 0\\n' > answer.py\n"
            'git add answer.py\n;; esac\n')
        hook.chmod(0o755)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('commit', result.stderr)
        self.assertNotEqual((self.proj / '.pipeline-checkpoint').read_text().strip(), 'complete')

    def test_review_cannot_add_pending_work_and_mark_project_complete(self):
        self.prepare()
        before = (self.proj / 'issues.md').read_bytes()
        (self.proj / 'answer.py').write_text('def answer():\n    return 0\n')
        self.git('add', '-A')
        self.git('commit', '-qm', 'Needs review repair')
        stub = self.root / 'bin/pi'
        code = stub.read_text().replace(
            'if scenario == "review_repaired":\n        implement()',
            'if scenario == "review_repaired":\n        implement()\n'
            '        with Path("issues.md").open("a") as stream:\n'
            '            stream.write("\\n## Issue #2: Pending feature\\nAdd another feature and tests.\\n")')
        stub.write_text(code)
        result = self.run_cli('--project', self.proj, '--resume', scenario='review_repaired')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj / 'issues.md').read_bytes(), before)
        self.assertNotEqual((self.proj / '.pipeline-checkpoint').read_text().strip(), 'complete')
        self.assertEqual(self.summaries('decision').count('Project complete: recovery-answer-cli'), 1)

    def test_failure_learning_cannot_commit_a_worker_written_completion(self):
        self.prepare()
        stub = self.root / 'bin/pi'
        code = stub.read_text().replace(
            'answer("execute2", "ISSUE_OK:',
            'graph = Path("kb/graph.json")\n'
            '    data = json.loads(graph.read_text())\n'
            '    data["nodes"].append({"id": "forged", "type": "decision", '
            '"summary": "Issue #2 completed", "detail": "uncommitted claim", "created_at": "now"})\n'
            '    graph.write_text(json.dumps(data))\n'
            '    answer("execute2", "ISSUE_OK:')
        stub.write_text(code)
        result = self.run_cli('--project', self.proj, '--iterate', 'Double answer')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('completion ledger', result.stderr)
        self.assertNotIn('Issue #2 completed', self.git('show', 'HEAD:kb/graph.json'))
        self.assertNotIn('double_answer', self.git('show', 'HEAD:answer.py'))
        self.assertIn('double_answer', (self.proj / 'answer.py').read_text())
