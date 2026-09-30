"""Additive APsystems adapter. Official End User manual v1.8, 2025-07-18.

No Linky dependency, no Excel writes. Network responses are never logged verbatim.
"""
from __future__ import annotations

import base64
import calendar
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://api.apsystemsema.com:9282"
PARIS = ZoneInfo("Europe/Paris")
LOCK = threading.Lock()
AUTO_LIMIT, TOTAL_LIMIT = 700, 900


class APError(Exception):
    def __init__(self, status="api_error", *, response_code=None, http_status=None):
        self.status = status
        self.response_code = response_code if type(response_code) is int else None
        self.http_status = http_status if type(http_status) is int else None
        super().__init__(status)  # Never include response, URL, headers or credentials.


APsystemsError = APError


class APsystemsAuthError(APError):
    pass


class APsystemsApiError(APError):
    pass


@dataclass(repr=False)
class Config:
    app_id: str
    secret: str
    sid: str
    mapping: dict = field(default_factory=dict)
    timestamp_unit: str = "seconds"  # Legacy argument; signing always uses seconds.
    automatic: bool = False
    base_url: str = BASE_URL


APsystemsConfig = Config


def load_config(path=ROOT / "config.local.json"):
    try:
        values = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            return None
        sid = values.get("APSYSTEMS_SID") or values.get("APSYSTEMS_SYSTEM_ID")
        credentials = [values.get("APSYSTEMS_APP_ID"), values.get("APSYSTEMS_APP_SECRET"), sid]
        if not all(isinstance(v, str) and v.strip() and not v.startswith("VOTRE_") for v in credentials):
            return None
        if any(v != v.strip() or any(ord(c) < 32 for c in v) for v in credentials):
            return None
        base_url = values.get("APSYSTEMS_BASE_URL", BASE_URL)
        if not isinstance(base_url, str) or base_url.rstrip("/") != BASE_URL:
            return None  # Never send credentials to an unverified destination.
        mapping = values.get("APSYSTEMS_ECU_MAPPING", {})
        if not isinstance(mapping, dict) or any(v not in ("MAIN", "PLUG") for v in mapping.values()):
            return None
        return Config(*credentials, mapping=mapping, timestamp_unit="seconds",
                      automatic=False, base_url=BASE_URL)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


load_apsystems_config = load_config


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    ensure_apsystems_schema(conn)
    return conn


def ensure_apsystems_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS apsystems_devices (
          sid TEXT, eid TEXT, timezone TEXT NOT NULL, inverters TEXT NOT NULL,
          PRIMARY KEY(sid,eid));
        CREATE TABLE IF NOT EXISTS apsystems_daily_production (
          sid TEXT, eid TEXT, date TEXT, kwh REAL, complete INTEGER NOT NULL,
          fetched_at TEXT NOT NULL, PRIMARY KEY(sid,eid,date));
        CREATE TABLE IF NOT EXISTS apsystems_power_curve (
          sid TEXT, eid TEXT, timestamp_utc TEXT, power_w REAL, energy_kwh REAL,
          PRIMARY KEY(sid,eid,timestamp_utc));
        CREATE TABLE IF NOT EXISTS apsystems_sync_meta (
          key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM apsystems_sync_meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(conn, key, value):
    conn.execute("INSERT INTO apsystems_sync_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, allow_nan=False)))


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise APError()
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise APError() from None
    if not math.isfinite(result) or result < 0:
        raise APError()
    return result


def generate_timestamp():
    # APsystems Support reference supplied on 2026-09-20: seconds, not milliseconds.
    return str(int(time.time()))


def generate_nonce():
    return str(uuid.uuid4()).replace('-', '')


def build_string_to_sign(app_id, url, timestamp, nonce):
    request_path = url.split('/')[-1]
    return f"{timestamp}/{nonce}/{app_id}/{request_path}/GET/HmacSHA256"


def sign_request(app_id, secret, url, timestamp, nonce):
    canonical = build_string_to_sign(app_id, url, timestamp, nonce)
    return base64.b64encode(hmac.new(secret.encode('utf-8'), canonical.encode('utf-8'),
                                   hashlib.sha256).digest()).decode('utf-8')


signature = sign_request


def redact_text(value, config, *sensitive):
    if not isinstance(value, str):
        return None
    for token in sorted({config.app_id, config.secret, config.sid, *config.mapping, *sensitive}, key=len, reverse=True):
        if token:
            value = value.replace(token, "[REDACTED]").replace(quote(token, safe=""), "[REDACTED]")
    return value


def response_shape(value, depth=0):
    """Types only, never API values (including authorization_code)."""
    if depth > 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): response_shape(v, depth+1) for k, v in value.items()}
    if isinstance(value, list):
        return {"type":"list", "length":len(value), "item":response_shape(value[0],depth+1) if value else None}
    return type(value).__name__


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise APError()  # Never forward signed headers to another host.


class Client:
    def __init__(self, config, opener=None, *, timestamp_factory=None, nonce_factory=None):
        self.config = config
        self.opener = opener or build_opener(NoRedirect()).open
        self.timestamp_factory = timestamp_factory or generate_timestamp
        self.nonce_factory = nonce_factory or generate_nonce
        self.last_diagnostic = {}

    def request(self, path, params):
        if self.config.base_url != BASE_URL or not path.startswith("/") or any(c in path for c in "?#\r\n"):
            raise APsystemsApiError("invalid_configuration")
        stamp = self.timestamp_factory()
        nonce = self.nonce_factory()
        url = self.config.base_url + path
        signed = sign_request(self.config.app_id, self.config.secret, url, stamp, nonce)
        self.last_diagnostic = {"endpoint":redact_text(url,self.config), "http_status":None,
            "timestamp":stamp, "timestamp_unit":"seconds", "nonce_length":len(nonce),
            "requestPath":redact_text(url.split('/')[-1],self.config), "request_method":"GET",
            "signature_method":"HmacSHA256", "api_code":None, "api_message":None,
            "stringToSign":f"{stamp}/<NONCE>/<APP_ID>/<LAST_PATH_SEGMENT>/GET/HmacSHA256"}
        headers = {"X-CA-AppId": self.config.app_id, "X-CA-Timestamp": stamp,
                   "X-CA-Nonce": nonce, "X-CA-Signature-Method": "HmacSHA256",
                   "X-CA-Signature": signed}
        req = Request(url + ("?" + urlencode(params) if params else ""), headers=headers, method="GET")
        try:
            with self.opener(req, timeout=20) as response:
                self.last_diagnostic["http_status"] = getattr(response, "status", None)
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise APError()
                payload = json.loads(raw)
        except HTTPError as exc:
            self.last_diagnostic["http_status"] = exc.code
            exc.close()
            error_type = APsystemsAuthError if exc.code in (401,403) else APsystemsApiError
            raise error_type("authentication_error" if exc.code in (401, 403) else "quota_warning" if exc.code == 429 else "api_error", http_status=exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise APError("offline") from None
        except (ValueError, UnicodeError):
            raise APError() from None
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise APError()
        code = payload["code"]
        self.last_diagnostic["api_code"] = code
        # Optional/undocumented message: preserve its name, never guess aliases.
        message = redact_text(payload.get("message"),self.config,signed,nonce)
        self.last_diagnostic["api_message"] = " ".join(message.split())[:500] if message else None
        self.last_diagnostic["message_present"] = "message" in payload
        shape = json.dumps(response_shape(payload), ensure_ascii=True)
        self.last_diagnostic["response_shape"] = json.loads(redact_text(shape,self.config,signed,nonce))
        if code != 0:
            status = "no_data" if code == 1001 else "authentication_error" if code in (2000,2001,2002,2003,2004,3000,3001,3002,3003,3004) else "quota_warning" if code in (2005,7000,7001,7002,7003) else "offline" if code == 6000 else "api_error"
            error_type = APsystemsAuthError if status == "authentication_error" else APsystemsApiError
            raise error_type(status, response_code=code, http_status=self.last_diagnostic["http_status"])
        if "data" not in payload:
            raise APError()
        return payload["data"]


APsystemsClient = Client


def test_connection(db_path, config, client=None, *, now=None):
    """Exactly one /details request, no retry/history/snapshot. Quota is accounted."""
    if not config:
        return {"status":"not_configured", "calls":0}
    if not LOCK.acquire(blocking=False):
        return {"status":"sync_in_progress", "calls":0}
    client = client or Client(config)
    calls = 0
    try:
        with closing(connect(db_path)) as conn:
            try:
                reserve_call(conn, now or datetime.now(timezone.utc), False)
                calls = 1
                data = client.request(f"/user/api/v2/systems/details/{quote(config.sid, safe='')}", {})
                if not isinstance(data, dict) or data.get("sid") != config.sid:
                    raise APsystemsApiError("response_validation_error")
                result = "ok"
            except APError as exc:
                result = exc.status
            return {**client.last_diagnostic, "status":result, "calls":calls}
    finally:
        LOCK.release()


def reserve_call(conn, now, automatic):
    month = now.astimezone(PARIS).strftime("%Y-%m")
    key = "calls:" + month
    conn.execute("BEGIN IMMEDIATE")
    counts = meta(conn, key, {"total": 0, "automatic": 0})
    if counts["total"] >= TOTAL_LIMIT or (automatic and counts["automatic"] >= AUTO_LIMIT):
        conn.rollback()
        raise APError("quota_warning")
    counts["total"] += 1
    counts["automatic"] += int(automatic)
    put(conn, key, counts)
    put(conn, "last_call", now.isoformat())
    conn.commit()  # Count attempts even on timeout, failure, or process interruption.


def parse_devices(payload, sid):
    if not isinstance(payload, list):
        raise APError()
    rows = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("eid"), str) or not item["eid"]:
            raise APError()
        tz = item.get("timezone")
        try:
            ZoneInfo(tz)
        except (TypeError, ValueError, KeyError):
            raise APError() from None
        inverters = item.get("inverter")
        if not isinstance(inverters, list) or any(not isinstance(v, dict) or not isinstance(v.get("uid"), str) for v in inverters):
            raise APError()
        rows.append((sid, item["eid"], tz, json.dumps([{"uid": v["uid"], "type": v.get("type")} for v in inverters])))
    if len({r[1] for r in rows}) != len(rows):
        raise APError()
    return rows


def parse_daily(payload, month, today):
    lengths = {calendar.monthrange(month.year, month.month)[1]}
    # Observed real API 2026-09-20: current month contains 20 ordered days,
    # not 30 future-padded entries. Do not accept arbitrary truncated history.
    if (month.year, month.month) == (today.year, today.month):
        lengths.add(today.day)
    if not isinstance(payload, list) or len(payload) not in lengths:
        raise APError()
    rows = []
    for i, value in enumerate(payload):
        day = month.replace(day=i+1)
        value = number(value)
        # Future padding is ignored. Today is never a completed daily measurement.
        if day <= today:
            rows.append((day.isoformat(), value, int(day < today and value is not None)))
    return rows


def parse_curve(payload, day, tz_name, now):
    if not isinstance(payload, dict):
        raise APError()
    times, power, energy = (payload.get(k) for k in ("time", "power", "energy"))
    if not all(isinstance(v, list) for v in (times, power, energy)) or not len(times) == len(power) == len(energy):
        raise APError()
    tz = ZoneInfo(tz_name)
    rows = []
    seen = set()
    for t, p, e in zip(times, power, energy):
        try:
            local = datetime.strptime(day.isoformat()+" "+t, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            raise APError() from None
        first, second = local.replace(tzinfo=tz, fold=0), local.replace(tzinfo=tz, fold=1)
        # No offset in API: ambiguous/nonexistent DST times cannot be aligned safely.
        if first.utcoffset() != second.utcoffset():
            continue
        utc = first.astimezone(timezone.utc)
        if utc > now or utc.isoformat() in seen:
            raise APError()
        seen.add(utc.isoformat())
        rows.append((utc.isoformat(), number(p), number(e)))
    return rows


def auto_slots(device_count):
    # Conservative daylight window in Albi: 10:00–16:00 Paris, no night calls.
    # Budget includes daily-month reads, previous-month closing and system status.
    cycles = max(0, min(4, (AUTO_LIMIT - 32*device_count - 33) // (31*(1+device_count))))
    return {0: [], 1: [12], 2: [10,16], 3: [10,13,16], 4: [10,12,14,16]}[cycles]


def sync(db_path, config, client=None, *, now=None, automatic=False, logger=None):
    if not config:
        return {"status": "not_configured", "calls": 0}
    if not LOCK.acquire(blocking=False):
        return {"status": "sync_in_progress", "calls": 0}
    now = now or datetime.now(timezone.utc)
    client = client or Client(config)
    calls, fetched = 0, 0
    error_detail = None
    last_endpoint = None
    try:
        with closing(connect(db_path)) as conn:
            def request(logical, path, params=None):
                nonlocal calls, last_endpoint
                last_endpoint = logical
                reserve_call(conn, now, automatic)
                calls += 1
                if logger:
                    logger.info("endpoint=%s tentative=%d", logical, calls)
                return client.request(path, params or {})

            try:
                sid = quote(config.sid, safe="")
                details_key = "details:"+config.sid
                details = meta(conn, details_key, {})
                if details.get("checked_day") != now.astimezone(PARIS).date().isoformat():
                    raw_details = request("details", f"/user/api/v2/systems/details/{sid}")
                    if not isinstance(raw_details, dict) or raw_details.get("sid") != config.sid or raw_details.get("light") not in (1,2,3,4):
                        raise APError()
                    try:
                        ZoneInfo(raw_details.get("timezone"))
                    except (ValueError, TypeError, KeyError):
                        raise APError() from None
                    details = {"timezone":raw_details["timezone"], "light":raw_details["light"],
                               "checked_day":now.astimezone(PARIS).date().isoformat()}
                    # Deliberately do not retain authorization_code or the raw response.
                    put(conn, details_key, details)
                    conn.commit()
                devices = list(conn.execute("SELECT * FROM apsystems_devices WHERE sid=? ORDER BY eid", (config.sid,)))
                if not devices:
                    detected = parse_devices(request("devices", f"/user/api/v2/systems/inverters/{sid}"), config.sid)
                    if not detected:
                        raise APError("no_data")
                    conn.executemany("INSERT INTO apsystems_devices VALUES (?,?,?,?) ON CONFLICT(sid,eid) DO UPDATE SET timezone=excluded.timezone,inverters=excluded.inverters", detected)
                    conn.commit()
                    devices = list(conn.execute("SELECT * FROM apsystems_devices WHERE sid=? ORDER BY eid", (config.sid,)))
                summary = request("summary", f"/user/api/v2/systems/summary/{sid}")
                if not isinstance(summary, dict) or not summary:
                    raise APError("no_data" if summary in ({}, None) else "api_error")
                summary = {k: number(summary.get(k)) for k in ("today", "month", "year", "lifetime")}
                if all(v is None for v in summary.values()):
                    raise APError("no_data")
                put(conn, "summary:"+config.sid, {**summary, "fetched_at": now.isoformat(),
                     "timezone":details["timezone"], "date":now.astimezone(ZoneInfo(details["timezone"])).date().isoformat()})
                conn.commit()
                for device in devices:
                    eid = quote(device["eid"], safe="")
                    base = f"/user/api/v2/systems/{sid}/devices/ecu/energy/{eid}"
                    today = now.astimezone(ZoneInfo(device["timezone"])).date()
                    month = today.replace(day=1)
                    months = [month]
                    # Close previous month once, including when recovering after downtime.
                    if today.day <= 7:
                        months.insert(0, (month - timedelta(days=1)).replace(day=1))
                    for target in months:
                        key = f"daily:{config.sid}:{device['eid']}:{target:%Y-%m}"
                        previous = meta(conn, key)
                        if previous == today.isoformat() or (target < month and previous and previous >= month.isoformat()):
                            continue
                        values = parse_daily(request("daily", base, {"energy_level":"daily", "date_range":target.strftime("%Y-%m")}), target, today)
                        conn.executemany("INSERT INTO apsystems_daily_production VALUES (?,?,?,?,?,?) ON CONFLICT(sid,eid,date) DO UPDATE SET kwh=excluded.kwh,complete=excluded.complete,fetched_at=excluded.fetched_at WHERE excluded.kwh IS NOT NULL",
                                         [(config.sid,device["eid"],d,v,c,now.isoformat()) for d,v,c in values])
                        put(conn, key, today.isoformat())
                        conn.commit()
                        fetched += sum(v is not None for _,v,_ in values)
                    curve = parse_curve(request("power", base, {"energy_level":"minutely", "date_range":today.isoformat()}), today, device["timezone"], now)
                    conn.executemany("INSERT INTO apsystems_power_curve VALUES (?,?,?,?,?) ON CONFLICT(sid,eid,timestamp_utc) DO UPDATE SET power_w=COALESCE(excluded.power_w,apsystems_power_curve.power_w),energy_kwh=COALESCE(excluded.energy_kwh,apsystems_power_curve.energy_kwh)",
                                     [(config.sid,device["eid"],*row) for row in curve])
                    fetched += len(curve)
                    conn.commit()
                put(conn, "last_success", now.isoformat())
                status = "ok" if fetched or summary else "no_data"
            except APError as exc:
                conn.rollback()
                status = exc.status
                error_detail = {"endpoint": last_endpoint, "response_code": exc.response_code, "http_status": exc.http_status}
            except Exception:
                conn.rollback()
                status = "api_error"
            put(conn, "last_status", status)
            put(conn, "last_error", error_detail)
            conn.commit()
            if logger:
                logger.info("statut=%s lignes=%d appels=%d", status, fetched, calls)
        return {"status":status, "calls":calls, "rows":fetched}
    finally:
        LOCK.release()


def rows(db_path, config, kind="daily", start=None, end=None):
    if not config or not Path(db_path).exists():
        return []
    table, column = ("apsystems_daily_production", "date") if kind == "daily" else ("apsystems_power_curve", "timestamp_utc")
    with closing(connect(db_path)) as conn:
        result = [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE sid=? ORDER BY {column},eid", (config.sid,))]
    for row in result:
        row.pop("sid", None)
        row["installation"] = config.mapping.get(row["eid"])
    return [r for r in result if (not start or r[column][:10] >= start) and (not end or r[column][:10] <= end)][-20000:]


def status(db_path, config, *, now=None):
    now = now or datetime.now(timezone.utc)
    output = {"configured":bool(config), "status":"not_configured" if not config else "never_synced",
              "last_sync":None, "last_data":None, "summary":None, "devices":[], "daily":[],
              "calls_month":0, "automatic_calls_month":0, "automatic_limit":AUTO_LIMIT, "local_limit":TOTAL_LIMIT,
              "current_power_w":None, "last_power_w":None, "last_power_at":None}
    if not config:
        return output
    with closing(connect(db_path)) as conn:
        output["status"] = meta(conn,"last_status","never_synced")
        output["last_sync"] = meta(conn,"last_success")
        output["last_error"] = meta(conn,"last_error")
        summary = meta(conn,"summary:"+config.sid)
        if summary:
            # A cached yesterday total must never be presented as today's production.
            summary = dict(summary)
            if summary.get("date") != now.astimezone(ZoneInfo(summary.get("timezone","Europe/Paris"))).date().isoformat():
                summary["today"] = None
        output["summary"] = summary
        output["communication"] = meta(conn,"details:"+config.sid)
        counts = meta(conn,"calls:"+now.astimezone(PARIS).strftime("%Y-%m"),{})
        output.update(calls_month=counts.get("total",0), automatic_calls_month=counts.get("automatic",0),last_call=meta(conn,"last_call"))
        for row in conn.execute("SELECT * FROM apsystems_devices WHERE sid=? ORDER BY eid",(config.sid,)):
            output["devices"].append({"eid":row["eid"],"timezone":row["timezone"],"inverters":json.loads(row["inverters"]),"installation":config.mapping.get(row["eid"])})
        latest = conn.execute("SELECT MAX(timestamp_utc) FROM apsystems_power_curve WHERE sid=?",(config.sid,)).fetchone()[0]
        if latest:
            values = list(conn.execute("SELECT power_w FROM apsystems_power_curve WHERE sid=? AND timestamp_utc=?",(config.sid,latest)))
            if len(values) == len(output["devices"]) and all(v[0] is not None for v in values):
                output["last_power_w"] = sum(v[0] for v in values)
                output["last_power_at"] = latest
                if 0 <= (now-datetime.fromisoformat(latest)).total_seconds() <= 1200:
                    output["current_power_w"] = output["last_power_w"]
        output["last_data"] = latest
    output["daily"] = rows(db_path,config)
    output["mapping_required"] = any(not d["installation"] for d in output["devices"])
    output["automatic_enabled"] = config.automatic
    output["automatic_hours_paris"] = auto_slots(len(output["devices"]))
    return output


def write_snapshot(db_path, config, path=ROOT / "site/apsystems-data.js"):
    payload = status(db_path, config)
    # Credentials are never part of status. Device IDs remain private local data.
    target = Path(path)
    temporary = target.with_suffix(".tmp")
    temporary.write_text("window.APSYSTEMS_DATA = " + json.dumps(payload,ensure_ascii=True,allow_nan=False) + ";\n",encoding="utf-8")
    temporary.replace(target)


def make_logger():
    logger = logging.getLogger("cockpit.apsystems")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        (ROOT/"logs").mkdir(exist_ok=True)
        handler = RotatingFileHandler(ROOT/"logs/apsystems.log",maxBytes=500000,backupCount=3,encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def automatic_tick(db_path, config, logger=None, now=None):
    # Support patch: manual only, including when a stale configuration enables auto.
    return
