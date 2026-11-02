"""Evaluation fixtures must reject broken products independently of model claims."""
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import phases, pi
from pipeline.evaluate import CASES, _run, check_product, evaluate


class IndependentChecks(unittest.TestCase):
    def test_profile_routes_are_copied_and_reported_per_live_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / 'models.json'
            models.write_text(json.dumps({role: {'model': 'local:latest', 'provider': 'ollama'}
                                          for role in ('planner', 'worker', 'consultant')}))
            selection = root / 'selection.json'
            selection.write_text(json.dumps({'phases': {'review': {
                'model': 'cloud:cloud', 'provider': 'ollama'}}}))
            target = root / 'case'
            target.mkdir()
            seen = []
            def fake_run(command, env, timeout, log):
                seen.append(command)
                self.assertEqual(json.loads((target / 'factory/config/models.json').read_text())
                                 ['worker']['model'], 'local:latest')
                self.assertEqual(json.loads((target / 'model-selection.json').read_text())
                                 ['phases']['review']['model'], 'cloud:cloud')
                return 1, 0.01
            with patch('pipeline.evaluate._run', side_effect=fake_run):
                result = evaluate('sum', target, 1, models_config=models,
                                  selection_file=selection)
            self.assertEqual(result['models']['worker']['model'], 'local:latest')
            self.assertEqual(result['selection']['phases']['review']['model'], 'cloud:cloud')
            self.assertEqual(seen[0][seen[0].index('--model-selection') + 1],
                             str((target / 'model-selection.json').resolve()))

    def test_evaluation_timeout_stops_child_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            late = root / 'late'
            pid_file = root / 'pid'
            child = f'import pathlib,time; time.sleep(0.7); pathlib.Path({str(late)!r}).touch()'
            parent = ('import os,pathlib,subprocess,sys,time; '
                      f'pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); '
                      f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(10)')
            try:
                code, _ = _run([sys.executable, '-c', parent], os.environ.copy(), 0.2, root / 'log')
                self.assertEqual(code, 124)
                time.sleep(0.8)
                self.assertFalse(late.exists(), 'A child survived the evaluation deadline')
            finally:
                if pid_file.exists():
                    try:
                        os.killpg(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_argument_validation_is_not_a_runtime_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / 'main.py').write_text('import sys\nif __name__ == "__main__":\n'
                '    print("Error: expected two integer arguments", file=sys.stderr)\n'
                '    sys.exit(1)\n')
            self.assertEqual(phases.runtime_smoke(project)[0], 'SKIPPED')

    def test_tracebacks_are_failures_even_if_they_mention_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / 'main.py').write_text('if __name__ == "__main__":\n    raise RuntimeError("usage")\n')
            self.assertEqual(phases.runtime_smoke(project)[0], 'FAILED')

    def test_correct_sum_passes_and_constant_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            cli = project / 'sum_cli.py'
            cli.write_text('import sys\nprint(int(sys.argv[1]) + int(sys.argv[2]))\n')
            self.assertTrue(all(row['passed'] for row in check_product(project, CASES['sum'])))
            cli.write_text('print(5)\n')
            self.assertFalse(all(row['passed'] for row in check_product(project, CASES['sum'])))

    def test_missing_script_cannot_pass_invalid_input_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = check_product(Path(directory), CASES['sum'])
            self.assertTrue(all(not row['passed'] for row in checks))

    def test_relative_project_paths_work_with_a_project_working_directory(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            project = Path(directory)
            (project / 'sum_cli.py').write_text('import sys\nprint(int(sys.argv[1]) + int(sys.argv[2]))\n')
            self.assertTrue(all(row['passed'] for row in check_product(project, CASES['sum'])))

    def test_call_metrics_measure_time_without_inventing_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with patch.object(pi, 'build_args', return_value=[sys.executable, '-c', 'print("ready")']):
                self.assertEqual(pi.run_pi('worker', '', '', cwd=project).strip(), 'ready')
            metric = json.loads((project / '.siesta/calls.jsonl').read_text())
            self.assertGreater(metric['seconds'], 0)
            self.assertEqual(metric['returncode'], 0)
            self.assertIsNone(metric['tokens'])
            self.assertIsNone(metric['cost'])
