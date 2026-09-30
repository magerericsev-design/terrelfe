"""Local-only web server for the classic solar cockpit and Linky API."""

from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import parse_qs, unquote, urlsplit

import apsystems_core as apsystems

from linky_core import (
    AuthError,
    ConfigError,
    LinkyError,
    MockClient,
    MyElectricalDataClient,
    ROOT,
    get_daily_rows,
    get_load_rows,
    get_status,
    load_config,
    sync_linky,
    write_public_snapshot,
)


SITE_DIR = (ROOT / "site").resolve()
SYNC_LOCK = threading.Lock()


def make_logger() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("cockpit.linky")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(log_dir / "linky.log", maxBytes=500_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = make_logger()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError("Date invalide; format attendu AAAA-MM-JJ.") from exc


class CockpitServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, mock: bool, db_path: Path):
        super().__init__(address, handler)
        self.mock = mock
        self.db_path = db_path
        self.config = None if mock else load_config(required=False)
        self.mock_failure: str | None = None
        self.apsystems_config = None if mock else apsystems.load_config()
        self.apsystems_client = None  # Injectable in isolated HTTP tests only.

    def client(self):
        if self.mock:
            return MockClient(failure=self.mock_failure)
        if not self.config:
            raise ConfigError("Configuration Linky absente.")
        return MyElectricalDataClient(self.config)


class Handler(BaseHTTPRequestHandler):
    server_version = "CockpitSolaireLocal/3"

    @property
    def app(self) -> CockpitServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args) -> None:
        # Do not persist URLs because query strings may contain private dates.
        LOGGER.info("HTTP %s", args[1] if len(args) > 1 else "request")

    def _headers(self, content_type: str, length: int | None = None) -> None:
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'")

    def json_response(self, status: int, payload: dict | list) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def error_response(self, exc: Exception, status: int | None = None) -> None:
        if isinstance(exc, AuthError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(exc, ConfigError):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(exc, LinkyError):
            status = HTTPStatus.SERVICE_UNAVAILABLE
        else:
            status = status or HTTPStatus.INTERNAL_SERVER_ERROR
        code = getattr(exc, "code", "server_error")
        self.json_response(int(status), {"ok": False, "error": code, "message": str(exc)[:300]})

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ConfigError("Requête invalide.") from exc
        if length > 32_768:
            raise ConfigError("Requête trop volumineuse.")
        if length == 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError("Corps JSON invalide.") from exc
        if not isinstance(value, dict):
            raise ConfigError("Objet JSON attendu.")
        return value

    def do_GET(self) -> None:
        route = urlsplit(self.path)
        if route.path in ("/api/apsystems/status", "/api/apsystems/daily", "/api/apsystems/power-curve"):
            try:
                if route.path.endswith("/status"):
                    result = apsystems.status(self.app.db_path, self.app.apsystems_config)
                else:
                    query = parse_qs(route.query)
                    start, end = [parse_date(query.get(k, [None])[0]) for k in ("start", "end")]
                    result = {"rows": apsystems.rows(self.app.db_path, self.app.apsystems_config,
                              "daily" if route.path.endswith("/daily") else "power",
                              start.isoformat() if start else None, end.isoformat() if end else None)}
                self.json_response(200, result)
            except Exception:
                self.json_response(503, {"status": "api_error", "message": "Lecture APsystems indisponible; données conservées."})
            return
        if route.path == "/api/health":
            self.json_response(200, {"ok": True, "service": "cockpit-solaire-linky", "mode": "mock" if self.app.mock else "real"})
            return
        if route.path == "/api/linky/status":
            self.json_response(200, get_status(self.app.db_path, configured=bool(self.app.config) or self.app.mock, mock=self.app.mock))
            return
        if route.path == "/api/linky/daily":
            try:
                query = parse_qs(route.query)
                rows = get_daily_rows(self.app.db_path, parse_date(query.get("start", [None])[0]), parse_date(query.get("end", [None])[0]))
                self.json_response(200, {"rows": rows})
            except Exception as exc:
                self.error_response(exc)
            return
        if route.path == "/api/linky/load-curve":
            try:
                query = parse_qs(route.query)
                kind = query.get("kind", ["consumption"])[0]
                if kind not in ("consumption", "production"):
                    raise ConfigError("kind doit valoir consumption ou production.")
                limit = int(query.get("limit", ["4000"])[0])
                rows = get_load_rows(self.app.db_path, kind, parse_date(query.get("start", [None])[0]), parse_date(query.get("end", [None])[0]), limit)
                self.json_response(200, {"kind": kind, "rows": rows})
            except Exception as exc:
                self.error_response(exc)
            return
        if route.path.startswith("/api/"):
            self.json_response(404, {"ok": False, "error": "not_found"})
            return
        self.serve_static(route.path)

    def do_POST(self) -> None:
        route = urlsplit(self.path)
        if route.path == "/api/apsystems/sync":
            # Same-origin JSON only: prevent an external page from spending API quota.
            origin = self.headers.get("Origin")
            if (origin and origin != f"http://127.0.0.1:{self.app.server_port}") or not self.headers.get("Content-Type", "").startswith("application/json"):
                self.json_response(403, {"status": "api_error", "message": "Origine ou format refusé."})
                return
            try:
                self.read_json()
                result = apsystems.sync(self.app.db_path, self.app.apsystems_config,
                                        self.app.apsystems_client, logger=apsystems.make_logger())
                if not self.app.mock and self.app.apsystems_client is None:
                    apsystems.write_snapshot(self.app.db_path, self.app.apsystems_config)
                self.json_response(200, {**result, "dashboard": apsystems.status(self.app.db_path, self.app.apsystems_config)})
            except Exception:
                self.json_response(503, {"status": "api_error", "message": "Synchronisation APsystems indisponible; données conservées."})
            return
        if route.path in ("/api/linky/sync", "/api/linky/import-history"):
            if not SYNC_LOCK.acquire(blocking=False):
                self.json_response(409, {"ok": False, "error": "sync_in_progress", "message": "Une synchronisation est déjà en cours."})
                return
            try:
                body = self.read_json()
                if self.app.mock:
                    failure = body.get("simulate")
                    self.app.mock_failure = failure if failure in ("offline", "invalid_token", "no_data") else None
                history_start = None
                if route.path.endswith("import-history"):
                    history_start = parse_date(body.get("start"))
                    if not history_start:
                        raise ConfigError("La date de début d'historique est obligatoire.")
                result = sync_linky(self.app.db_path, self.app.client(), history_start=history_start, logger=LOGGER)
                if not self.app.mock:
                    write_public_snapshot(self.app.db_path, SITE_DIR / "linky-data.js", configured=True)
                self.json_response(200, {"ok": True, **result, "dashboard": get_status(self.app.db_path, configured=True, mock=self.app.mock)})
            except Exception as exc:
                self.error_response(exc)
            finally:
                SYNC_LOCK.release()
            return
        if route.path == "/api/linky/shutdown":
            self.json_response(200, {"ok": True})
            threading.Thread(target=self.app.shutdown, daemon=True).start()
            return
        self.json_response(404, {"ok": False, "error": "not_found"})

    def serve_static(self, raw_path: str) -> None:
        relative = unquote(raw_path).lstrip("/") or "index.html"
        candidate = (SITE_DIR / relative).resolve()
        try:
            candidate.relative_to(SITE_DIR)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        raw = candidate.read_bytes()
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or candidate.suffix in (".js", ".json"):
            mime += "; charset=utf-8"
        self.send_response(200)
        self._headers(mime, len(raw))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serveur local du cockpit solaire classique")
    parser.add_argument("--mock", action="store_true", help="utilise exclusivement des données de démonstration")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    config = None if args.mock else load_config(required=False)
    port = args.port or (8766 if args.mock else config.port if config else 8765)
    db_path = ROOT / "data" / ("energy-demo.db" if args.mock else "energy.db")
    server = CockpitServer(("127.0.0.1", port), Handler, mock=args.mock, db_path=db_path)
    pid_path = ROOT / "data" / f"linky-server-{port}.pid"
    pid_path.parent.mkdir(exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    LOGGER.info("Serveur local démarré en mode %s sur le port %d", "test" if args.mock else "réel", port)
    apsystems_stop = threading.Event()
    def apsystems_worker():
        while not apsystems_stop.wait(60):
            try:
                apsystems.automatic_tick(db_path, server.apsystems_config, apsystems.make_logger())
            except Exception:
                apsystems.make_logger().warning("Synchronisation automatique indisponible")
    threading.Thread(target=apsystems_worker, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        apsystems_stop.set()
        server.server_close()
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        LOGGER.info("Serveur local arrêté")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
