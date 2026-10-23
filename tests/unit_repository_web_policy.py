"""Keep website source eligible without admitting local recordings or backups."""
import importlib.util
from pathlib import Path
import unittest

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repository_audit', root / 'tools/check_repository.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class WebsiteSourcePolicyTests(unittest.TestCase):
    def test_reviewed_source_is_allowed(self):
        for path in ('frontend/index.html', 'frontend/app.js', 'frontend/style.css',
                     'backend/server.py', 'tests/test_history.py', 'tests/test_masks.py'):
            with self.subTest(path=path):
                self.assertFalse(audit.private_path('Jarvis-Web/' + path))

    def test_other_website_files_stay_private(self):
        for path in ('backups/old/server.py', 'frontend/.env', 'tools/cloudflared',
                     'frontend/style.css.backup', 'backend/server_backup.py',
                     'backend/__pycache__/server.pyc', 'tests/capture.png',
                     'frontend/new-unreviewed.js', 'state.json', 'events.jsonl'):
            with self.subTest(path=path):
                self.assertTrue(audit.private_path('Jarvis-Web/' + path))

    def test_capture_and_profile_roots_remain_private(self):
        for path in ('Masks/runs/example/manifest.json', 'Footage/frame.jpg',
                     'VoiceProfiles/person/profile.json', 'data/captains-log/entry.mp4'):
            with self.subTest(path=path):
                self.assertTrue(audit.private_path(path))

if __name__ == '__main__':
    unittest.main()
