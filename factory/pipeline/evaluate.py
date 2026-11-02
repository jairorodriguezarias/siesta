"""Reproducible live-model checks with independent CLI assertions.

Run: PYTHONPATH=factory python3 -m pipeline.evaluate --output .runtime/evaluation
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline.__main__ import slug
from pipeline.pi import FACTORY, ROLE


CASES = {
    'sum': {
        'idea': 'Build a Python CLI sum_cli.py using only the standard library. '
                'Use one implementation issue with pytest tests. '
                'It accepts exactly two positional integers and prints only their sum followed by a newline. '
                'Negative integers work. Invalid integers exit nonzero and explain the error on stderr. '
                'No packaging, GUI, server, dependencies or extra features.',
        'script': 'sum_cli.py',
        'checks': [(['2', '3'], '5\n'), (['-7', '2'], '-5\n'), (['oops', '2'], None)],
    },
    'slug': {
        'idea': 'Build a Python CLI slugify.py using only the standard library. '
                'Use one implementation issue with pytest tests. '
                'It accepts exactly one positional string. Convert ASCII letters to lowercase, '
                'replace every run of characters outside a-z and 0-9 with one hyphen, '
                'strip leading and trailing hyphens, and print the result followed by a newline. '
                'An empty input prints only a newline. Missing or extra arguments exit nonzero with stderr. '
                'No packaging, GUI, server, dependencies or extra features.',
        'script': 'slugify.py',
        'checks': [(['Hello, WORLD!'], 'hello-world\n'), ([' A__B 42 '], 'a-b-42\n'),
                   ([''], '\n'), ([], None), (['one', 'two'], None)],
    },
}


def check_product(proj: Path, case: dict) -> list[dict]:
    """Execute fixed inputs; never read expected outputs from generated tests."""
    proj = proj.resolve()
    results = []
    script = proj / case['script']
    for args, expected in case['checks']:
        try:
            if not script.is_file() or script.is_symlink():
                raise ValueError('Expected CLI file is missing or is a symlink')
            proc = subprocess.run([sys.executable, str(script), *args], cwd=proj,
                                  capture_output=True, text=True, timeout=10)
            passed = (proc.returncode != 0 and bool(proc.stderr.strip())) if expected is None else (
                proc.returncode == 0 and proc.stdout == expected)
            results.append({'args': args, 'passed': passed, 'returncode': proc.returncode,
                            'stdout': proc.stdout, 'stderr': proc.stderr})
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            results.append({'args': args, 'passed': False, 'error': str(exc)})
    return results


def _run(command: list[str], env: dict, timeout: int, log: Path) -> tuple[int, float]:
    started = time.monotonic()
    with log.open('w') as output, subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, start_new_session=True) as proc:
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Let run_pi's finally block reap its separate process group.
            os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = 124
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return code, round(time.monotonic() - started, 3)


def evaluate(case_id: str, destination: Path, timeout: int) -> dict:
    case = CASES[case_id]
    factory = destination / 'factory'
    for name in ('agents', 'config', 'skills', 'pipeline'):
        shutil.copytree(FACTORY / name, factory / name)
    (factory / 'kb').mkdir()
    for name in ('schema.json', 'global-seed.json'):
        shutil.copy2(FACTORY / 'kb' / name, factory / 'kb' / name)
    shutil.copytree(FACTORY.parent / '.agents/skills', destination / '.agents/skills')
    env = {**os.environ, 'SIESTA_FACTORY': str(factory.resolve()),
           'PYTHONPATH': str(factory.resolve()),
           'SIESTA_PI_TIMEOUT': str(min(timeout, 180)),
           'GIT_AUTHOR_NAME': 'Siesta Evaluation', 'GIT_AUTHOR_EMAIL': 'evaluation@example.invalid',
           'GIT_COMMITTER_NAME': 'Siesta Evaluation', 'GIT_COMMITTER_EMAIL': 'evaluation@example.invalid'}
    command = [sys.executable, '-B', '-m', 'pipeline', '--auto', case['idea']]
    code, elapsed = _run(command, env, timeout, destination / 'console.log')
    proj = factory / 'projects' / slug(case['idea'])
    checks = check_product(proj, case)
    metric_file = proj / '.siesta/calls.jsonl'
    calls = metric_file.read_text().splitlines() if metric_file.exists() else []
    checkpoint = proj / '.pipeline-checkpoint'
    verdict = proj / 'verify_verdict.txt'
    success = (code == 0 and checkpoint.exists() and checkpoint.read_text().strip() == 'complete'
               and verdict.exists() and verdict.read_text().strip() == 'VERIFY_PASSED'
               and all(check['passed'] for check in checks))
    resume = None
    if success:
        before = subprocess.check_output(['git', '-C', str(proj), 'rev-parse', 'HEAD'])
        resume_code, _ = _run(command, env, timeout, destination / 'resume.log')
        resume = (resume_code == 0 and metric_file.read_text().splitlines() == calls
                  and subprocess.check_output(['git', '-C', str(proj), 'rev-parse', 'HEAD']) == before)
        success = success and resume
    source_digest = hashlib.sha256()
    source_files = list((factory / 'pipeline').glob('*.py'))
    source_files.extend((factory / 'agents').glob('*.md'))
    for path in sorted(source_files):
        source_digest.update(path.name.encode() + b'\0' + path.read_bytes())
    return {'case': case_id, 'passed': success, 'exit_code': code, 'seconds': elapsed,
            'source_sha256': source_digest.hexdigest(),
            'model_calls': len(calls), 'tokens': None, 'cost': None,
            'human_interventions': 0, 'resume_unchanged': resume, 'checks': checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, action='append')
    parser.add_argument('--timeout', type=int, default=600, help='Maximum seconds per case')
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / '.gitignore').write_text('*\n')
    report = {'date': datetime.now(timezone.utc).isoformat(), 'models': ROLE, 'results': [],
              'measurement': 'Wall time and call count measured; text-mode Pi exposes no token/cost totals.'}
    for index, case in enumerate(args.case or CASES, 1):
        destination = args.output / f'{index}-{case}'
        report['results'].append(evaluate(case, destination, args.timeout))
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report['results'][-1]), flush=True)
    raise SystemExit(0 if all(row['passed'] for row in report['results']) else 1)


if __name__ == '__main__':
    main()
