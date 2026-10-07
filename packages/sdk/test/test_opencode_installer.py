import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / 'skills/tervik/scripts/install-opencode.py'
spec = importlib.util.spec_from_file_location('opencode_installer', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class OpenCodeInstallation(unittest.TestCase):
    def test_reinstall_preserves_credentials_identity_and_unrelated_plugins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plugins').mkdir()
            unrelated = root / 'plugins/other.js'
            unrelated.write_text('existing plugin')
            installer.install(root, 'http://127.0.0.1:8000', 'test-project-key')
            original = json.loads((root / 'tervik.json').read_text())
            installer.install(root)
            self.assertEqual(json.loads((root / 'tervik.json').read_text()), original)
            self.assertEqual(unrelated.read_text(), 'existing plugin')
            self.assertEqual(stat.S_IMODE((root / 'tervik.json').stat().st_mode), 0o600)
            self.assertNotIn('test-project-key', (root / 'plugins/tervik.js').read_text())
            self.assertEqual((root / 'tervik/opencode-plugin.mjs').read_bytes(), (SCRIPT.parent / 'opencode-plugin.mjs').read_bytes())
            self.assertEqual((root / 'tervik/tervik-client.mjs').read_bytes(), (SCRIPT.parent / 'tervik-client.mjs').read_bytes())

    def test_missing_key_does_not_invent_a_credential(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root)
            config = json.loads((root / 'tervik.json').read_text())
            self.assertIn('userId', config)
            self.assertNotIn('apiKey', config)
            self.assertNotIn('endpoint', config)


if __name__ == '__main__':
    unittest.main()
