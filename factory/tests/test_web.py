"""Local desktop HTTP request boundaries."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pipeline.web.runner import Desktop
from pipeline.web.server import make_server


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.desktop = Desktop(Path(self.tmp.name))
        self.addCleanup(self.desktop.close)
        self.server = make_server(self.desktop, port=0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port

    def request(self, path, *, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_static_assets_and_session_are_local(self):
        status, content, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Snake.exe', content)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        status, content, _ = self.request('/api/session')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(content)['token'])

    def test_remote_host_origin_and_missing_token_are_rejected(self):
        self.assertEqual(self.request('/api/session', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/session', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/run', method='POST', body='{}',
                         headers={'Content-Type': 'application/json'})[0], 403)

    def test_traversal_and_non_object_json_are_rejected(self):
        self.assertEqual(self.request('/../config/models.json')[0], 404)
        status, content, _ = self.request('/api/session')
        token = json.loads(content)['token']
        status, _, _ = self.request('/api/run', method='POST', body='[]', headers={
            'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 400)

    def test_model_selection_reaches_the_desktop_runner(self):
        _, content, _ = self.request('/api/session')
        token = json.loads(content)['token']
        selection = {'phases': {'planning': {
            'model': 'planner-local', 'provider': 'ollama'}}}
        with patch.object(self.desktop, 'start', return_value={'status': 'running'}) as start:
            status, _, _ = self.request('/api/run', method='POST',
                body=json.dumps({'idea': 'A small CLI', 'model_selection': selection}),
                headers={'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 200)
        start.assert_called_once_with('A small CLI', auto=False,
                                     model_selection=selection)

    def test_model_catalog_and_check_keep_server_token_boundary(self):
        from pipeline import model_catalog
        with patch.object(model_catalog, 'catalog', return_value={
                'models': [{'id': 'local:latest', 'origin': 'local'}]}) as listing:
            status, content, _ = self.request('/api/models')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)['models'][0]['id'], 'local:latest')
        listing.assert_called_once_with(self.desktop.factory)
        body = json.dumps({'model': 'local:latest', 'tools': True})
        self.assertEqual(self.request('/api/models/check', method='POST', body=body,
                                     headers={'Content-Type': 'application/json'})[0], 403)
        _, session, _ = self.request('/api/session')
        token = json.loads(session)['token']
        with patch.object(model_catalog, 'check_compatibility', return_value={
                'status': 'compatible'}) as check:
            status, content, _ = self.request('/api/models/check', method='POST',
                body=body, headers={'Content-Type': 'application/json',
                                    'X-Siesta-Token': token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), {'status': 'compatible'})
        check.assert_called_once_with(self.desktop.factory, model='local:latest',
                                      provider='ollama', tools=True)


if __name__ == '__main__':
    unittest.main()
