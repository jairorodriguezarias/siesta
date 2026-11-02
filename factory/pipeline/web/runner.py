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

from .. import references, reviews
from ..kb import Graph

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
        from .. import model_selection as selections
        try:
            defaults = json.loads((self.factory / 'config' / 'models.json').read_text())
        except FileNotFoundError:
            from ..pi import ROLE
            defaults = ROLE
        selected = selections.load_project(project) or selections.normalize_selection(
            {}, role_defaults=defaults)
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
            'model_selection': selected,
            'review_policy': reviews.project_policy(project),
        }

    def document(self, name, document):
        if document not in DOCUMENTS:
            raise ValueError('Unknown document')
        path = self._file(self._project(name), document)
        if not path.is_file():
            raise ValueError('Document not found')
        return read_text(path)

    def _knowledge_graph(self, scope, project=None):
        if scope == 'global' and project is None:
            path = self.factory / 'kb/global-graph.json'
            seed = self.factory / 'kb/global-seed.json'
        elif scope == 'project' and isinstance(project, str):
            root = self._project(project)
            if not root.is_dir():
                raise ValueError('Project not found')
            path = self._file(root, 'kb/graph.json')
            if not path.is_file():
                raise ValueError('Project KB not found')
            seed = None
        else:
            raise ValueError('Choose a global or project KB')
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('KB path cannot be a symlink')
        return Graph(path, seed=seed)

    def knowledge(self, scope, project=None, query='', type_=None, offset=0):
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError('Search must be at most 200 characters')
        if type_ is not None and (not isinstance(type_, str)
                                  or not re.fullmatch(r'[a-z_]{1,40}', type_)):
            raise ValueError('Invalid KB type')
        if type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError('Invalid KB offset')
        nodes = self._knowledge_graph(scope, project).query(type_=type_, summary_only=False)
        if query:
            needle = query.casefold()
            nodes = [node for node in nodes if needle in node['summary'].casefold()
                     or needle in node['type'].casefold()
                     or needle in node['detail'].casefold()]
        nodes.reverse()
        return {'nodes': [{key: node[key] for key in ('id', 'type', 'summary', 'created_at')}
                          for node in nodes[offset:offset + 100]],
                'total': len(nodes), 'offset': offset}

    def knowledge_item(self, scope, node_id, project=None):
        if not isinstance(node_id, str) or not re.fullmatch(r'n[0-9]+_[0-9]+', node_id):
            raise ValueError('Invalid KB node')
        graph = self._knowledge_graph(scope, project)
        node = graph.get(node_id)
        if node is None:
            raise ValueError('KB node not found')
        result = dict(node)
        if len(result.get('detail', '')) > LIMIT:
            result['detail'] = result['detail'][:LIMIT]
            result['truncated'] = True
        names = {item['id']: item['summary'] for item in graph.data['nodes']}
        result['relations'] = [
            {'type': edge['type'], 'direction': 'out' if edge['from'] == node_id else 'in',
             'id': edge['to'] if edge['from'] == node_id else edge['from'],
             'summary': names.get(edge['to'] if edge['from'] == node_id else edge['from'],
                                  '(missing node)')}
            for edge in graph.data['edges']
            if edge['from'] == node_id or edge['to'] == node_id
        ][:100]
        return result

    def add_reference(self, summary, detail):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise Conflict('Wait for the active project before editing the KB')
            graph = self._knowledge_graph('global')
            node_id = references.add(graph, summary, detail)
            return graph.get(node_id)

    def start(self, idea, *, auto=False, command=None, model_selection=None,
              review_policy=None):
        if not isinstance(idea, str) or not idea.strip() or len(idea) > 12000 or '\x00' in idea:
            raise ValueError('Describe an idea using 1–12000 characters')
        if not isinstance(auto, bool):
            raise ValueError('auto must be a boolean')
        if review_policy is not None and review_policy not in ('normal', 'deep'):
            raise ValueError('review policy must be normal or deep')
        selection_file = None
        if model_selection is not None:
            if command is not None:
                raise ValueError('model selection requires the Siesta CLI runner')
            try:
                from .. import model_selection as selections
                defaults = json.loads((self.factory / 'config' / 'models.json').read_text())
                existing = selections.load_project(self._project(slug(idea)))
                normalized = selections.from_overrides(model_selection,
                                                       role_defaults=(existing or {}).get(
                                                           'role_defaults', defaults))
                from ..model_catalog import catalog
                available = {row['id']: row for row in catalog(self.factory)['models']}
                previous = existing or {'phases': {}, 'agents': {}}
                routes = [route for phase, route in normalized['phases'].items()
                          if route != previous['phases'].get(phase)]
                routes.extend(
                    route for phase, agents in normalized['agents'].items()
                    for agent, route in agents.items()
                    if route != previous['agents'].get(phase, {}).get(agent))
                for route in routes:
                    entry = available.get(route['model'])
                    if (route['provider'] != 'ollama' or entry is None
                            or entry['preparation'] is not None):
                        raise ValueError(f"Model {route['model']} needs Pi/Ollama preparation")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f'Invalid model selection: {exc}') from exc
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
            if model_selection is not None:
                selection_file = run_dir / 'model-selection.json'
                selection_file.write_text(json.dumps({
                    'phases': normalized['phases'], 'agents': normalized['agents'],
                }))
            env = {**os.environ, 'SIESTA_FACTORY': str(self.factory),
                   'SIESTA_STATUS_FILE': str(status_file), 'PYTHONUNBUFFERED': '1',
                   'PYTHONPATH': str(Path(__file__).resolve().parents[2])
                   + os.pathsep + os.environ.get('PYTHONPATH', '')}
            args = command if command is not None else (
                [sys.executable, '-u', '-m', 'pipeline.web.worker']
                + (['--model-selection', str(selection_file)] if selection_file else [])
                + (['--review-policy', review_policy] if review_policy else [])
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
                    'agent': state.get('agent'), 'model': state.get('model'),
                    'provider': state.get('provider'),
                    'model_phase': state.get('model_phase'),
                    'review': state.get('review'),
                    'tokens': state.get('tokens'), 'cost': state.get('cost'),
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
