import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPT = Path(__file__).resolve().parents[3] / 'skills/tervik/scripts/status-opencode.py'
spec = importlib.util.spec_from_file_location('opencode_status', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OpenCodeStatus(unittest.TestCase):
    def test_credentials_do_not_reach_output_or_dashboard_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plugins').mkdir()
            (root / 'plugins/tervik.js').write_text('plugin')
            (root / 'tervik.json').write_text(json.dumps({'endpoint': 'http://localhost:8000', 'apiKey': 'INGEST_SECRET'}))
            requests = []
            def response(request, timeout):
                requests.append(request)
                data = {'/api/health': {'status': 'ok'}, '/api/projects': [{'id': 'p1', 'name': 'OpenCode'}], '/api/projects/p1/setup': {'events_received': 4, 'conversations': 1, 'last_event_at': '2026-10-07T21:21:08Z', 'jobs': {'failed': 0}}}[request.selector]
                return io.BytesIO(json.dumps(data).encode())
            with patch.dict('os.environ', {'TERVIK_ADMIN_TOKEN': 'ADMIN_SECRET'}, clear=True), patch.object(module, 'urlopen', response):
                report = module.status(root)
            self.assertTrue(report['plugin_installed'])
            self.assertTrue(report['key_configured'])
            self.assertEqual(report['projects'][0]['events_received'], 4)
            self.assertNotIn('INGEST_SECRET', json.dumps(report))
            self.assertNotIn('ADMIN_SECRET', json.dumps(report))
            self.assertTrue(all(r.get_header('Authorization') == 'Bearer ADMIN_SECRET' for r in requests))

    def test_dashboard_auth_failure_does_not_reuse_ingest_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tervik.json').write_text(json.dumps({'apiKey': 'INGEST_SECRET'}))
            def response(request, timeout):
                self.assertIsNone(request.get_header('Authorization'))
                if request.selector == '/api/health':
                    return io.BytesIO(b'{"status":"ok"}')
                raise HTTPError(request.full_url, 403, 'Denied', {}, None)
            with patch.dict('os.environ', {}, clear=True), patch.object(module, 'urlopen', response):
                report = module.status(root)
            self.assertEqual(report['verification'], 'dashboard_auth_required')
            self.assertNotIn('INGEST_SECRET', json.dumps(report))

    def test_credential_bearing_endpoint_is_not_printed_or_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tervik.json').write_text(json.dumps({'endpoint': 'http://user:URL_SECRET@localhost:8000'}))
            with patch.dict('os.environ', {}, clear=True), patch.object(module, 'urlopen') as read:
                report = module.status(root)
            read.assert_not_called()
            self.assertEqual(report['verification'], 'invalid_endpoint')
            self.assertNotIn('URL_SECRET', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
