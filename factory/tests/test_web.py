"""Local desktop HTTP request boundaries."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

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


if __name__ == '__main__':
    unittest.main()
