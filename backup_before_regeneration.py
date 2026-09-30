#!/usr/bin/env python3
"""Create a compact rollback ZIP before each regeneration; keep recent copies."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "backups" / "auto"
KEEP = 12

files = [ROOT / "KWH.xlsx", ROOT / "site" / "data.js", ROOT / "site" / "weather-data.js", ROOT / "site" / "linky-data.js"]
DEST.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
out = DEST / f"avant-regeneration-{stamp}.zip"
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in files:
        if path.exists():
            zf.write(path, path.relative_to(ROOT))
    database = ROOT / "data" / "energy.db"
    if database.exists():
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "energy.db"
            with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as destination:
                source.backup(destination)
            zf.write(snapshot, "data/energy.db")

old = sorted(DEST.glob("avant-regeneration-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
for path in old[KEEP:]:
    path.unlink(missing_ok=True)
print(f"Sauvegarde de sécurité: {out.name}")
