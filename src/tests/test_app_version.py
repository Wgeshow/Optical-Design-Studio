from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app_version


class AppVersionTests(unittest.TestCase):
    def test_missing_or_older_receipt_does_not_invent_update_date(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app_version, 'application_root', return_value=Path(folder)):
            self.assertEqual(app_version.installation_info()['last_updated'], 'Not recorded')
            receipt = Path(folder) / 'installation.json'
            for text in ('{broken', '[]', '{"version":"1.0.1","updated_at":"2026-09-13T10:00:00"}',
                         json.dumps({'version': app_version.APP_VERSION, 'updated_at': 'bad'})):
                receipt.write_text(text)
                self.assertEqual(app_version.installation_info()['last_updated'], 'Not recorded')

    def test_installation_receipt_and_platform(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app_version, 'application_root', return_value=Path(folder)), \
                patch.object(app_version.platform, 'system', return_value='Windows'), \
                patch.object(app_version.platform, 'machine', return_value='AMD64'), \
                patch.object(app_version.struct, 'calcsize', return_value=8):
            (Path(folder) / 'installation.json').write_text(json.dumps({
                'version': app_version.APP_VERSION, 'updated_at': '2026-09-13T10:00:00'}))
            result = app_version.installation_info()
            self.assertEqual(result['version'], app_version.APP_VERSION)
            self.assertEqual(result['last_updated'], 'September 13, 2026')
            self.assertEqual(result['platform_id'], 'windows-x64')


if __name__ == '__main__':
    unittest.main()
