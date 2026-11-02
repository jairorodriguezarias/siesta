"""Serialize CLI runs and expose bounded, read-only project evidence."""
import json
import fcntl
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from ..__main__ import slug

DOCUMENTS = ('spec.md', 'issues.md', '.siesta/design-review.md',
             '.siesta/requirements.md', 'verify_verdict.txt')
LIMIT = 65536
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


class Conflict(ValueError):
    """An operation does not match the current run/input state."""


def read_text(path: Path, *, tail=False) -> str:
    try:
        with path.open('rb') as stream:
            if tail:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - LIMIT))
            return stream.read(LIMIT).decode('utf-8', errors='replace')
    except FileNotFoundError:
        return ''


class Desktop:
    def __init__(self, factory: Path):
        self.factory = factory.resolve()
        self.factory_lock = (self.factory / '.siesta-desktop.lock').open('a')
        try:
            fcntl.flock(self.factory_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.factory_lock.close()
            raise Conflict('Another desktop already owns this factory') from exc
        self.runtime = tempfile.TemporaryDirectory(prefix='siesta-desktop-')
        self.lock = threading.RLock()
        self.process = None
        self.run = None
        self.log = None
        self.status_file = None
        self.answered_id = None
        self.finished = None

    def _project(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', name):
            raise ValueError('Invalid project name')
        root = (self.factory / 'projects').resolve()
        project = root / name
        if project.is_symlink() or not project.resolve().is_relative_to(root):
            raise ValueError('Project must be inside this factory')
        return project

    def _file(self, project, name):
        path = project / name
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError('Document must be inside this project')
        return path

    def projects(self):
        root = self.factory / 'projects'
        if not root.exists():
            return []
        result = []
        for path in sorted(root.iterdir(), key=lambda p: p.name):
            if len(result) >= 200:
                break
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                project = self._project(path.name)
                result.append(self.project(project.name))
            except (ValueError, OSError):
                continue
        return result

    def project(self, name):
        project = self._project(name)
        if not project.is_dir():
            raise ValueError('Project not found')
        documents = []
        for document in DOCUMENTS:
            try:
                if self._file(project, document).is_file():
                    documents.append(document)
            except ValueError:
                continue
        return {
            'name': name,
            'idea': read_text(self._file(project, '.pipeline-idea')).strip(),
            'checkpoint': read_text(self._file(project, '.pipeline-checkpoint')).strip(),
            'verdict': read_text(self._file(project, 'verify_verdict.txt')).strip(),
            'stopped': self._file(project, 'stop.md').exists(),
            'documents': documents,
        }

    def document(self, name, document):
        if document not in DOCUMENTS:
            raise ValueError('Unknown document')
        path = self._file(self._project(name), document)
        if not path.is_file():
            raise ValueError('Document not found')
        return read_text(path)

    def start(self, idea, *, auto=False, command=None):
        if not isinstance(idea, str) or not idea.strip() or len(idea) > 12000 or '\x00' in idea:
            raise ValueError('Describe an idea using 1–12000 characters')
        if not isinstance(auto, bool):
            raise ValueError('auto must be a boolean')
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise Conflict('Siesta is already working on a project')
            idea = idea.strip()
            name = slug(idea)
            self._project(name)
            run_id = uuid.uuid4().hex
            run_dir = Path(self.runtime.name) / run_id
            run_dir.mkdir()
            status_file = run_dir / 'status.json'
            log = run_dir / 'console.log'
            env = {**os.environ, 'SIESTA_FACTORY': str(self.factory),
                   'SIESTA_STATUS_FILE': str(status_file), 'PYTHONUNBUFFERED': '1',
                   'PYTHONPATH': str(Path(__file__).resolve().parents[2])
                   + os.pathsep + os.environ.get('PYTHONPATH', '')}
            args = command if command is not None else (
                [sys.executable, '-u', '-m', 'pipeline.web.worker']
                + (['--auto'] if auto else []) + ['--', idea])
            with log.open('wb') as output:
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=output,
                                           stderr=subprocess.STDOUT, env=env,
                                           cwd=self.factory, start_new_session=True)
            if self.process is not None and self.process.stdin:
                self.process.stdin.close()
            self.process = process
            self.log, self.status_file = log, status_file
            self.answered_id, self.finished = None, None
            self.run = {'id': run_id, 'project': name, 'idea': idea,
                        'started': time.time()}
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            if self.run is None:
                return {'status': 'idle'}
            state = {}
            try:
                state = json.loads(read_text(self.status_file) or '{}')
            except (ValueError, OSError):
                pass
            if state.get('project'):
                self._project(state['project'])
                self.run['project'] = state['project']
            code = self.process.poll()
            input_id = state.get('input_id')
            if input_id == self.answered_id or code is not None:
                input_id = None
            status = 'waiting' if input_id else 'running'
            if code is not None:
                if self.finished is None:
                    self.finished = time.time()
                try:
                    project = self.project(self.run['project'])
                except (ValueError, OSError):
                    project = {}
                status = 'incomplete'
                if code != 0:
                    status = 'failed'
                elif project.get('stopped'):
                    status = 'stopped'
                elif project.get('checkpoint') == 'complete' and project.get('verdict') == 'VERIFY_PASSED':
                    status = 'complete'
            return {**self.run, 'status': status, 'phase': str(state.get('phase', '')),
                    'input_id': input_id, 'returncode': code,
                    'elapsed': (self.finished or time.time()) - self.run['started'],
                    'output': ANSI.sub('', read_text(self.log, tail=True))}

    def reply(self, run_id, input_id, answer):
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000 or any(c in answer for c in '\r\n\x00'):
            raise ValueError('Write one nonempty line, up to 12000 characters')
        with self.lock:
            state = self.snapshot()
            if state['status'] != 'waiting' or state['id'] != run_id or state['input_id'] != input_id:
                raise Conflict('This interview question is no longer waiting for an answer')
            try:
                self.process.stdin.write((answer + '\n').encode())
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise Conflict('The interview process has ended') from exc
            self.answered_id = input_id
            return self.snapshot()

    def close(self):
        with self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=3)
                if self.process.stdin:
                    self.process.stdin.close()
            self.runtime.cleanup()
            if not self.factory_lock.closed:
                fcntl.flock(self.factory_lock, fcntl.LOCK_UN)
                self.factory_lock.close()
