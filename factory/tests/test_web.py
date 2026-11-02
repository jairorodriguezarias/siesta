"""Local desktop HTTP request boundaries."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from pipeline.kb import Graph
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
                body=json.dumps({'idea': 'A small CLI', 'name': 'Small CLI',
                                 'model_selection': selection}),
                headers={'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 200)
        start.assert_called_once_with('A small CLI', auto=False,
                                     model_selection=selection, review_policy=None,
                                     display_name='Small CLI', project=None)

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

    def test_review_policy_reaches_runner(self):
        _, session, _ = self.request('/api/session')
        token = json.loads(session)['token']
        with patch.object(self.desktop, 'start', return_value={'status': 'running'}) as start:
            status, _, _ = self.request('/api/run', method='POST',
                body=json.dumps({'idea': 'Review deeply', 'name': 'Deep review',
                                 'review_policy': 'deep'}),
                headers={'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 200)
        start.assert_called_once_with('Review deeply', auto=False,
                                      model_selection=None, review_policy='deep',
                                      display_name='Deep review', project=None)

    def test_resume_keeps_the_selected_project_directory(self):
        project = self.desktop.factory / 'projects/imported-project'
        project.mkdir(parents=True)
        (project / '.pipeline-idea').write_text('Original idea')
        _, session, _ = self.request('/api/session')
        process = Mock()
        process.poll.return_value = 0
        with patch('pipeline.web.runner.subprocess.Popen', return_value=process) as popen:
            status, _, _ = self.request('/api/run', method='POST',
                body=json.dumps({'project': 'imported-project'}), headers={
                    'Content-Type': 'application/json',
                    'X-Siesta-Token': json.loads(session)['token']})
        self.assertEqual(status, 200)
        args = popen.call_args.args[0]
        self.assertIn('--project', args)
        self.assertEqual(args[args.index('--project') + 1], str(project))

    def test_project_management_and_stop_require_token_and_name(self):
        _, session, _ = self.request('/api/session')
        token = json.loads(session)['token']
        headers = {'Content-Type': 'application/json', 'X-Siesta-Token': token}
        self.assertEqual(self.request('/api/run', method='POST',
            body=json.dumps({'idea': 'Timer'}), headers=headers)[0], 400)
        self.assertEqual(self.request('/api/run', method='POST',
            body=json.dumps({'idea': 'Timer', 'name': None}), headers=headers)[0], 400)
        self.assertEqual(self.request('/api/stop', method='POST',
            body='{"run_id":"x"}', headers={'Content-Type': 'application/json'})[0], 403)
        with patch.object(self.desktop, 'stop', return_value={'status': 'stopped'}) as stop:
            self.assertEqual(self.request('/api/stop', method='POST',
                body='{"run_id":"run-1"}', headers=headers)[0], 200)
            stop.assert_called_once_with('run-1')
        with patch.object(self.desktop, 'rename_project', return_value={
                'display_name': 'New title'}) as rename:
            self.assertEqual(self.request('/api/project/rename', method='POST',
                body='{"project":"timer","name":"New title"}', headers=headers)[0], 200)
            rename.assert_called_once_with('timer', 'New title')
        with patch.object(self.desktop, 'delete_project', return_value={
                'deleted': 'timer'}) as delete:
            self.assertEqual(self.request('/api/project/delete', method='POST',
                body='{"project":"timer","confirm":"timer"}', headers=headers)[0], 200)
            delete.assert_called_once_with('timer', 'timer')

    def test_knowledge_list_detail_and_add_require_local_token(self):
        self.assertEqual(self.request('/api/knowledge?scope=global')[0], 200)
        body = json.dumps({'summary': 'Audience', 'detail': 'Readers on phones'})
        self.assertEqual(self.request('/api/knowledge', method='POST', body=body,
                                     headers={'Content-Type': 'application/json'})[0], 403)
        _, session, _ = self.request('/api/session')
        token = json.loads(session)['token']
        status, added, _ = self.request('/api/knowledge', method='POST', body=body,
            headers={'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 200)
        node_id = json.loads(added)['id']
        status, listed, _ = self.request('/api/knowledge?scope=global')
        self.assertEqual(status, 200)
        self.assertTrue(any(item['id'] == node_id for item in json.loads(listed)['nodes']))
        status, detail, _ = self.request('/api/knowledge/item?scope=global&id=' + node_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(detail)['detail'], 'Readers on phones')
        self.assertEqual(self.request('/api/knowledge?scope=project&project=../evil')[0], 404)

    def test_project_knowledge_is_scoped_and_writes_wait_for_idle_run(self):
        project = Path(self.tmp.name) / 'projects/reader'
        graph = Graph(project / 'kb/graph.json')
        intent_id = graph.node('intent', 'Reader app', 'Read local files')
        decision_id = graph.node('decision', 'Offline', 'Keep data local')
        graph.edge(decision_id, intent_id, 'applied_to')
        status, content, _ = self.request('/api/knowledge?scope=project&project=reader&q=local')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)['total'], 2)
        status, detail, _ = self.request('/api/knowledge/item?scope=project&project=reader&id=' + intent_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(detail)['relations'][0]['summary'], 'Offline')
        self.assertEqual(self.request('/api/knowledge?scope=project&project=missing')[0], 404)
        _, session, _ = self.request('/api/session')
        token = json.loads(session)['token']
        body = json.dumps({'summary': 'Later', 'detail': 'Do not write during a run'})
        from unittest.mock import Mock
        self.desktop.process = Mock()
        self.desktop.process.poll.return_value = None
        status, _, _ = self.request('/api/knowledge', method='POST', body=body,
            headers={'Content-Type': 'application/json', 'X-Siesta-Token': token})
        self.assertEqual(status, 409)
        self.desktop.process = None


if __name__ == '__main__':
    unittest.main()
