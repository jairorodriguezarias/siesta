"""Loopback-only HTTP adapter. No arbitrary paths, shell commands or HTML output."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from .runner import Conflict

ASSETS = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/desktop.css': ('desktop.css', 'text/css; charset=utf-8'),
    '/responsive.css': ('responsive.css', 'text/css; charset=utf-8'),
    '/desktop.mjs': ('desktop.mjs', 'text/javascript; charset=utf-8'),
    '/model_picker.mjs': ('model_picker.mjs', 'text/javascript; charset=utf-8'),
    '/game.mjs': ('game.mjs', 'text/javascript; charset=utf-8'),
    '/snake.mjs': ('snake.mjs', 'text/javascript; charset=utf-8'),
    '/icon.svg': ('icon.svg', 'image/svg+xml'),
}


def make_server(desktop, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            hosts = {f'127.0.0.1:{self.server.server_port}',
                     f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') not in hosts
                    or origin is not None and origin not in {f'http://{h}' for h in hosts}
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.send(403, {'error': 'This desktop accepts local requests only'})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            try:
                if url.path in ASSETS:
                    name, content_type = ASSETS[url.path]
                    self.send(200, Path(__file__).with_name(name).read_bytes(), content_type)
                elif url.path == '/api/session':
                    self.send(200, {'token': token})
                elif url.path == '/api/run':
                    self.send(200, desktop.snapshot())
                elif url.path == '/api/projects':
                    self.send(200, {'projects': desktop.projects()})
                elif url.path == '/api/models':
                    from ..model_catalog import catalog
                    self.send(200, catalog(desktop.factory))
                elif url.path == '/api/document':
                    content = desktop.document(query.get('project', [''])[0],
                                               query.get('name', [''])[0])
                    self.send(200, {'content': content, 'limit': 65536})
                elif url.path == '/api/knowledge':
                    self.send(200, desktop.knowledge(
                        query.get('scope', ['global'])[0],
                        query.get('project', [None])[0],
                        query.get('q', [''])[0], query.get('type', [None])[0],
                        int(query.get('offset', ['0'])[0])))
                elif url.path == '/api/knowledge/item':
                    self.send(200, desktop.knowledge_item(
                        query.get('scope', ['global'])[0],
                        query.get('id', [''])[0], query.get('project', [None])[0]))
                else:
                    self.send(404, {'error': 'Not found'})
            except (ValueError, OSError):
                self.send(404, {'error': 'Document or project unavailable'})

        def do_POST(self):
            if not self.local_request():
                return
            if not secrets.compare_digest(self.headers.get('X-Siesta-Token', '').encode(), token.encode()):
                self.send(403, {'error': 'Refresh the desktop to reconnect to this server'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Request must be between 1 and 65536 bytes')
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Send JSON content')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                if self.path == '/api/run':
                    idea = body.get('idea')
                    if 'project' in body:
                        idea = desktop.project(body['project'])['idea']
                    state = desktop.start(idea, auto=body.get('auto', False),
                                          model_selection=body.get('model_selection'),
                                          review_policy=body.get('review_policy'))
                elif self.path == '/api/reply':
                    state = desktop.reply(body.get('run_id'), body.get('input_id'), body.get('answer'))
                elif self.path == '/api/models/check':
                    from ..model_catalog import check_compatibility
                    if set(body) - {'model', 'provider', 'tools'}:
                        raise ValueError('Unknown model check field')
                    state = check_compatibility(desktop.factory, model=body.get('model'),
                                                provider=body.get('provider', 'ollama'),
                                                tools=body.get('tools', True))
                elif self.path == '/api/knowledge':
                    if set(body) != {'summary', 'detail'}:
                        raise ValueError('A reference needs title and text')
                    state = desktop.add_reference(body['summary'], body['detail'])
                else:
                    self.send(404, {'error': 'Not found'})
                    return
                self.send(200, state)
            except Conflict as exc:
                self.send(409, {'error': str(exc)})
            except (ValueError, UnicodeError) as exc:
                self.send(400, {'error': str(exc)})
            except OSError:
                self.send(500, {'error': 'Could not access the project or start the pipeline'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
