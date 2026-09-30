"""Integration tests on a disposable copy; never contact real energy accounts."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ANDROID = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANDROID / 'app/build/generated/cockpit/python'))
sys.path.insert(0, str(ANDROID / 'app/src/main/python'))
import mobile_backend as mobile


class MobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / 'cockpit'
        shutil.copytree(ANDROID / 'app/build/generated/cockpit/assets/cockpit', cls.root)
        cls.url = mobile.start(str(cls.root))

    @classmethod
    def tearDownClass(cls):
        mobile.SERVER.shutdown()
        mobile.SERVER.server_close()
        cls.temp.cleanup()

    def get(self, route):
        with urlopen(self.url + route, timeout=10) as response:
            return json.loads(response.read())

    def test_health_and_historical_data(self):
        self.assertTrue(self.get('/api/health')['ok'])
        self.assertGreater(len(self.get('/api/linky/daily')['rows']), 0)
        self.assertFalse(self.get('/api/linky/status')['configured'])
        with urlopen(self.url + '/assets/cockpit-solaire-logo-96.png') as response:
            self.assertEqual(response.status, 200)

    def test_no_credentials_or_private_files_served(self):
        for path in ('/config.local.json', '/energy.db', '/KWH.xlsx', '/api/linky/shutdown'):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        self.assertFalse(any(p.name == 'config.local.json' for p in (ANDROID / 'app/build/generated/cockpit').rglob('*')))

    def test_reject_external_mutations_without_spending_quota(self):
        for origin in (None, 'https://example.org'):
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            for route in ('/api/linky/sync', '/api/apsystems/sync'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(self.url + route, data=b'{}', headers=headers))
                self.assertEqual(error.exception.code, 403)

    def test_settings_validation_and_manual_mode(self):
        with self.assertRaises(Exception):
            mobile.save_settings(json.dumps({'MYELECTRICALDATA_TOKEN': 'fake', 'LINKY_PDL': '1'}))
        self.assertFalse((self.root / 'config.local.json').exists())
        mobile.save_settings(json.dumps({'APSYSTEMS_AUTO_SYNC': True, 'MAPPING_JSON': '{}'}))
        stored = json.loads(mobile.read_settings())
        self.assertFalse(stored['APSYSTEMS_AUTO_SYNC'])
        self.assertIsNone(mobile.SERVER.config)
        import linky_core
        self.assertIsNone(linky_core.load_config(required=False))
        with self.assertRaises(ValueError):
            mobile.save_settings(json.dumps({'MAPPING_JSON': '{"ecu": "INVALID"}'}))
        self.assertEqual(json.loads(mobile.read_settings()), stored)
        (self.root / 'config.local.json').unlink()

    def test_excel_import_uses_uploaded_workbook(self):
        uploaded = self.root / 'import.xlsx'
        shutil.copy2(self.root / 'KWH.xlsx', uploaded)
        self.assertTrue(mobile.import_workbook(str(uploaded)))
        self.assertFalse(uploaded.exists())
        self.assertIn('SOLAR_DASHBOARD_DATA', (self.root / 'site/data.js').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
