"""Bundle only application assets; never include Windows runtimes or credentials."""
from pathlib import Path
import shutil
import sqlite3

ANDROID = Path(__file__).resolve().parents[1]
ROOT = ANDROID.parent
OUT = ANDROID / 'app/build/generated/cockpit'
SITE = OUT / 'assets/cockpit/site'
PYTHON = OUT / 'python'
for directory in (SITE / 'assets', PYTHON, OUT / 'assets/cockpit/data'):
    directory.mkdir(parents=True, exist_ok=True)
for name in ('index.html', 'app.js', 'styles.css', 'home-design.css', 'product-finish.css',
             'data.js', 'weather-data.js', 'linky-data.js', 'apsystems-data.js'):
    shutil.copy2(ROOT / name, SITE / name)
for pattern in ('*.png', '*.svg', '*.ico'):
    for asset in ROOT.glob(pattern):
        shutil.copy2(asset, SITE / 'assets' / asset.name)
for name in ('linky_core.py', 'apsystems_core.py', 'linky_server.py',
             'build_from_export_site.py', 'build_weather_from_meteofrance.py'):
    shutil.copy2(ROOT / name, PYTHON / name)
with sqlite3.connect(f'file:{ROOT / "energy.db"}?mode=ro&immutable=1', uri=True) as source:
    with sqlite3.connect(OUT / 'assets/cockpit/data/energy.db') as destination:
        source.backup(destination)
shutil.copy2(ROOT / 'KWH.xlsx', OUT / 'assets/cockpit/KWH.xlsx')
# Add mobile styling only to the generated Android copy.
html = (SITE / 'index.html').read_text(encoding='utf-8')
html = html.replace('</head>', '<link rel="stylesheet" href="android.css"></head>')
(SITE / 'index.html').write_text(html, encoding='utf-8')
(SITE / 'android.css').write_text('''
html, body { overflow-x: hidden; }
button, select, input, .v3-nav a { min-height: 44px; }
@media (max-width: 600px) {
  .v3-nav { display: flex; overflow-x: auto; gap: 6px; padding-bottom: 8px; }
  .v3-nav a { flex: 0 0 auto; white-space: nowrap; }
  .v3-sidebar { padding: 12px; }
  .v3-main { padding: 12px; }
  .panel { padding: 14px; }
  .brand h1 { font-size: 20px; }
  .topbar h2 { font-size: 22px; }
}
''', encoding='utf-8')
assert not list(OUT.rglob('config.local.json'))
