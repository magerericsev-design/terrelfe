"""Android lifecycle adapter. Original desktop modules remain unchanged."""
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

ROOT = None
SERVER = None
LOCK = threading.RLock()


def start(root):
    global ROOT, SERVER
    with LOCK:
        if SERVER:
            return f'http://127.0.0.1:{SERVER.server_port}'
        ROOT = Path(root)
        import linky_core as linky
        import apsystems_core as apsystems
        linky.ROOT = ROOT
        apsystems.ROOT = ROOT
        original_linky_load = linky.load_config
        def load_linky(path=None, *, required=True):
            try:
                return original_linky_load(path, required=required)
            except linky.ConfigError:
                if required:
                    raise
                return None
        linky.load_config = load_linky
        # The desktop default argument captured its original root at import time.
        original_load = apsystems.load_config
        apsystems.load_config = lambda: original_load(ROOT / 'config.local.json')
        import linky_server as desktop
        desktop.ROOT = ROOT
        desktop.SITE_DIR = (ROOT / 'site').resolve()

        class MobileHandler(desktop.Handler):
            def do_POST(self):
                # Every mutation requires the WebView's own JSON origin.
                if (self.headers.get('Origin') != f'http://127.0.0.1:{self.app.server_port}'
                        or not self.headers.get('Content-Type', '').startswith('application/json')):
                    self.json_response(403, {'ok': False, 'message': 'Origine refusée.'})
                    return
                if urlsplit(self.path).path == '/api/linky/shutdown':
                    self.json_response(404, {'ok': False})
                    return
                super().do_POST()

            def serve_static(self, raw_path):
                # Credentials, workbook and database live outside SITE_DIR.
                super().serve_static(raw_path)

        SERVER = desktop.CockpitServer(('127.0.0.1', 0), MobileHandler,
                                       mock=False, db_path=ROOT / 'data/energy.db')
        threading.Thread(target=SERVER.serve_forever, daemon=True).start()
        return f'http://127.0.0.1:{SERVER.server_port}'


def read_settings():
    path = ROOT / 'config.local.json'
    return path.read_text() if path.exists() else '{}'


def save_settings(raw):
    import linky_core as linky
    import apsystems_core as apsystems
    values = json.loads(raw)
    values['APSYSTEMS_AUTO_SYNC'] = False
    values['APSYSTEMS_BASE_URL'] = apsystems.BASE_URL
    values['PORT'] = 8765
    values['LINKY_START_DATE'] = values.get('LINKY_START_DATE') or '2025-01-01'
    mapping = json.loads(values.pop('MAPPING_JSON', '{}') or '{}')
    if not isinstance(mapping, dict) or any(v not in ('MAIN', 'PLUG') for v in mapping.values()):
        raise ValueError('Mapping ECU invalide : utiliser MAIN ou PLUG.')
    values['APSYSTEMS_ECU_MAPPING'] = mapping
    path = ROOT / 'config.local.json'
    temporary = ROOT / 'config.pending.json'
    temporary.write_text(json.dumps(values), encoding='utf-8')
    try:
        linky_config = None
        if values.get('MYELECTRICALDATA_TOKEN') or values.get('LINKY_PDL'):
            linky_config = linky.load_config(temporary)
        # APsystems validates its canonical domain and identifiers itself.
        present = [bool(values.get(k)) for k in ('APSYSTEMS_APP_ID', 'APSYSTEMS_APP_SECRET', 'APSYSTEMS_SID')]
        if any(present) and not all(present):
            raise ValueError('Renseignez les trois champs APsystems ou laissez-les vides.')
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        SERVER.config = linky_config
        SERVER.apsystems_config = apsystems.load_config()
    finally:
        temporary.unlink(missing_ok=True)
    return True


def update_weather():
    import build_weather_from_meteofrance as weather
    data = weather.build_weather_data(weather.parse_args([]))
    temporary = ROOT / 'site/weather-data.pending.js'
    weather.write_weather_data(data, temporary)
    temporary.replace(ROOT / 'site/weather-data.js')
    return True


def import_workbook(path):
    import build_from_export_site as builder
    data = builder.build_dashboard_data(Path(path))
    builder.write_dashboard_data(data, ROOT / 'site')
    Path(path).replace(ROOT / 'KWH.xlsx')
    return True
