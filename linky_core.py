"""Core Linky/MyElectricalData logic for the classic local dashboard.

Only Python's standard library is used so the cockpit remains portable. Secrets
are read locally and are never returned by the public functions in this module.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
API_BASE = "https://www.myelectricaldata.fr"
STREAMS = {
    "daily_consumption": ("daily_consumption", "daily_consumption"),
    "daily_production": ("daily_production", "daily_production"),
    "load_consumption": ("consumption_load_curve", "load_consumption"),
    "load_production": ("production_load_curve", "load_production"),
    "daily_max_power": ("daily_consumption_max_power", "daily_max_power"),
}


class LinkyError(RuntimeError):
    code = "linky_error"


class ConfigError(LinkyError):
    code = "not_configured"


class AuthError(LinkyError):
    code = "authorization_required"


class TemporaryError(LinkyError):
    code = "temporarily_unavailable"


class RateLimitError(LinkyError):
    code = "rate_limited"


class NoDataError(LinkyError):
    code = "no_data"


class ApiError(LinkyError):
    code = "api_error"


@dataclass(frozen=True)
class LinkyConfig:
    token: str
    pdl: str
    start_date: date
    port: int = 8765


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(path: Path | None = None, *, required: bool = True) -> LinkyConfig | None:
    config_path = path or ROOT / "config.local.json"
    if not config_path.exists():
        if required:
            raise ConfigError("Configuration Linky absente. Copiez config.example.json vers config.local.json.")
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("Le fichier config.local.json est illisible ou invalide.") from exc
    token = str(raw.get("MYELECTRICALDATA_TOKEN", "")).strip()
    pdl = "".join(c for c in str(raw.get("LINKY_PDL", "")) if c.isdigit())
    if len(token) < 8 or len(pdl) not in (12, 13, 14):
        raise ConfigError("Le jeton MyElectricalData ou le numéro PDL est absent/invalide.")
    try:
        start = date.fromisoformat(str(raw.get("LINKY_START_DATE", "2025-01-01")))
        port = int(raw.get("PORT", 8765))
    except (TypeError, ValueError) as exc:
        raise ConfigError("LINKY_START_DATE ou PORT est invalide dans config.local.json.") from exc
    if not 1024 <= port <= 65535:
        raise ConfigError("PORT doit être compris entre 1024 et 65535.")
    return LinkyConfig(token=token, pdl=pdl, start_date=start, port=port)


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_consumption (
            day TEXT PRIMARY KEY, energy_wh REAL NOT NULL, quality TEXT,
            source_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_production (
            day TEXT PRIMARY KEY, energy_wh REAL NOT NULL, quality TEXT,
            source_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS load_consumption (
            timestamp_utc TEXT PRIMARY KEY, timestamp_local TEXT NOT NULL,
            value_w REAL NOT NULL, interval_minutes INTEGER, measure_type TEXT,
            source_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS load_production (
            timestamp_utc TEXT PRIMARY KEY, timestamp_local TEXT NOT NULL,
            value_w REAL NOT NULL, interval_minutes INTEGER, measure_type TEXT,
            source_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_max_power (
            day TEXT PRIMARY KEY, power_va REAL NOT NULL, source_updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            stream TEXT PRIMARY KEY, last_success_at TEXT, last_data_at TEXT,
            last_request_start TEXT, last_request_end TEXT, status TEXT NOT NULL,
            error_code TEXT, error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _reading(payload: dict[str, Any]) -> dict[str, Any]:
    reading = payload.get("meter_reading", payload)
    if not isinstance(reading, dict):
        raise NoDataError("Réponse Linky sans bloc meter_reading.")
    return reading


def _unit_factor(unit: str | None, target: str) -> float:
    cleaned = (unit or target).strip().lower()
    factors = {
        "wh": 1.0, "kwh": 1000.0, "mwh": 1_000_000.0,
        "w": 1.0, "kw": 1000.0, "va": 1.0, "kva": 1000.0,
    }
    return factors.get(cleaned, 1.0)


def _numeric(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _interval_minutes(value: Any) -> int | None:
    number = _numeric(value)
    if number is not None:
        return int(number)
    text = str(value or "").upper()
    if text.startswith("PT") and text.endswith("M"):
        number = _numeric(text[2:-1])
        return int(number) if number is not None else None
    return None


def parse_day(value: str) -> str:
    text = str(value).strip()
    try:
        if len(text) >= 10:
            return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    raise NoDataError(f"Date Linky invalide: {text[:24]}")


def normalize_timestamp(value: str) -> tuple[str, str]:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NoDataError(f"Horodatage Linky invalide: {str(value)[:24]}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PARIS)
    local = parsed.astimezone(PARIS)
    utc = parsed.astimezone(UTC)
    return (
        utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        local.isoformat(timespec="seconds"),
    )


def parse_daily(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reading = _reading(payload)
    unit = str((reading.get("reading_type") or {}).get("unit", "Wh"))
    factor = _unit_factor(unit, "Wh")
    quality = str(reading.get("quality", ""))
    rows: list[dict[str, Any]] = []
    for item in reading.get("interval_reading") or []:
        number = _numeric(item.get("value"))
        if number is None:
            continue
        rows.append({"day": parse_day(item.get("date", "")), "value": number * factor, "quality": quality})
    return rows


def parse_load_curve(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reading = _reading(payload)
    unit = str((reading.get("reading_type") or {}).get("unit", "W"))
    factor = _unit_factor(unit, "W")
    rows: list[dict[str, Any]] = []
    for item in reading.get("interval_reading") or []:
        number = _numeric(item.get("value"))
        if number is None:
            continue
        utc, local = normalize_timestamp(item.get("date", ""))
        interval = _interval_minutes(item.get("interval_length"))
        rows.append({
            "timestamp_utc": utc,
            "timestamp_local": local,
            "value": number * factor,
            "interval_minutes": interval,
            "measure_type": str(item.get("measure_type", "")),
        })
    return rows


def parse_max_power(payload: dict[str, Any]) -> list[dict[str, Any]]:
    reading = _reading(payload)
    unit = str((reading.get("reading_type") or {}).get("unit", "VA"))
    factor = _unit_factor(unit, "VA")
    rows = []
    for item in reading.get("interval_reading") or []:
        number = _numeric(item.get("value"))
        if number is not None:
            rows.append({"day": parse_day(item.get("date", "")), "value": number * factor})
    return rows


class MyElectricalDataClient:
    def __init__(
        self,
        config: LinkyConfig,
        *,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        retries: int = 2,
        timeout: int = 30,
    ) -> None:
        self.config = config
        self.opener = opener
        self.sleeper = sleeper
        self.retries = retries
        self.timeout = timeout

    def _get(self, path: str) -> dict[str, Any]:
        request = Request(
            f"{API_BASE}{path}",
            headers={"Authorization": self.config.token, "Accept": "application/json", "User-Agent": "Cockpit-Solaire-Local/2"},
        )
        for attempt in range(self.retries + 1):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise AuthError("Autorisation MyElectricalData absente ou expirée.") from exc
                if exc.code == 404:
                    raise NoDataError("Aucune donnée Linky disponible pour cette période.") from exc
                if exc.code == 429:
                    retry_after = None
                    try:
                        retry_after = float(exc.headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        pass
                    if retry_after is not None and retry_after <= 30 and attempt < self.retries:
                        self.sleeper(max(1.0, retry_after))
                        continue
                    raise RateLimitError("Limite MyElectricalData atteinte; réessayez plus tard.") from exc
                if 500 <= exc.code <= 599:
                    if attempt < self.retries:
                        self.sleeper(0.5 * (2**attempt))
                        continue
                    raise TemporaryError("Service MyElectricalData temporairement indisponible.") from exc
                raise ApiError(f"Erreur MyElectricalData HTTP {exc.code}.") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self.sleeper(0.5 * (2**attempt))
                    continue
                raise TemporaryError("Connexion Internet/MyElectricalData indisponible.") from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError("Réponse MyElectricalData illisible.") from exc
        raise TemporaryError("Service MyElectricalData indisponible.")

    def valid_access(self) -> dict[str, Any]:
        payload = self._get(f"/valid_access/{self.config.pdl}")
        if payload.get("valid") is False:
            raise AuthError("Consentement Enedis/MyElectricalData invalide ou expiré.")
        return payload

    def fetch(self, endpoint: str, start: date, end: date) -> dict[str, Any]:
        return self._get(f"/{endpoint}/{self.config.pdl}/start/{start.isoformat()}/end/{end.isoformat()}")


class MockClient:
    """Deterministic provider. It never reads a real token or PDL."""

    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.config = LinkyConfig("DEMO-NO-SECRET", "00000000000000", date(2025, 1, 1), 8766)

    def _fail(self) -> None:
        if self.failure == "offline":
            raise TemporaryError("Mode test: connexion simulée indisponible.")
        if self.failure == "invalid_token":
            raise AuthError("Mode test: autorisation simulée expirée.")
        if self.failure == "no_data":
            raise NoDataError("Mode test: aucune donnée simulée.")

    def valid_access(self) -> dict[str, Any]:
        self._fail()
        return {"valid": True, "consent_expiration_date": "2027-09-05", "quota_reached": False, "call_number": 6, "quota_limit": 50}

    def fetch(self, endpoint: str, start: date, end: date) -> dict[str, Any]:
        self._fail()
        if end < start:
            return {"meter_reading": {"interval_reading": []}}
        days = (end - start).days + 1
        if "load_curve" in endpoint:
            values = []
            # MyElectricalData load curves are energy intervals in [start, end),
            # returned with timestamps at the *end* of each interval: (start, end].
            cursor = datetime.combine(start, datetime.min.time(), PARIS) + timedelta(minutes=30)
            stop = datetime.combine(end, datetime.min.time(), PARIS)
            index = 0
            while cursor < stop:
                hour = cursor.hour + cursor.minute / 60
                if endpoint.startswith("production"):
                    daylight = max(0.0, math.sin(math.pi * (hour - 7) / 12))
                    value = round(2100 * daylight, 1)
                else:
                    value = round(310 + 520 * (hour in (7, 8, 12, 19, 20)) + 55 * math.sin(int(cursor.timestamp() / 1800) / 5), 1)
                values.append({"value": max(0, value), "date": cursor.isoformat(), "interval_length": "PT30M", "measure_type": "B"})
                cursor = (cursor.astimezone(UTC) + timedelta(minutes=30)).astimezone(PARIS)
                index += 1
            return {"meter_reading": {"quality": "DEMO", "reading_type": {"unit": "W"}, "interval_reading": values}}
        values = []
        for index in range(days):
            current = start + timedelta(days=index)
            season = 0.65 + 0.35 * math.sin(2 * math.pi * (current.timetuple().tm_yday - 80) / 365)
            if endpoint == "daily_production":
                value = round(max(0.0, 5800 * season + 350 * math.sin(current.toordinal() * 1.7)))
                unit = "Wh"
            elif endpoint == "daily_consumption_max_power":
                value = round(2350 + 500 * abs(math.sin(current.toordinal() * 0.7)))
                unit = "VA"
            else:
                value = round(8700 - 2400 * season + 700 * abs(math.sin(current.toordinal() * 1.1)))
                unit = "Wh"
            values.append({"value": value, "date": current.isoformat()})
        return {"meter_reading": {"quality": "DEMO", "reading_type": {"unit": unit}, "interval_reading": values}}


def date_chunks(start: date, end: date, max_days: int) -> Iterable[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def load_curve_chunks(
    start: date,
    end: date,
    max_days: int = 7,
    overlap_days: int = 1,
) -> Iterable[tuple[date, date]]:
    """Yield load-curve API windows with an exclusive end and safe overlap.

    The public API documentation names start/end but does not state inclusivity.
    Real responses show interval-end timestamps in ``(start, end]``; therefore a
    request represents energy in ``[start, end)``. ``end`` here is the last local
    calendar day wanted, so the final API bound is ``end + 1 day``.
    """
    if end < start:
        return
    if max_days < 1 or overlap_days < 0 or overlap_days >= max_days:
        raise ValueError("Découpage de courbe invalide.")
    exclusive_stop = end + timedelta(days=1)
    cursor = start
    while cursor < exclusive_stop:
        chunk_end = min(exclusive_stop, cursor + timedelta(days=max_days))
        yield cursor, chunk_end
        if chunk_end >= exclusive_stop:
            break
        cursor = chunk_end - timedelta(days=overlap_days)


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_curve_quality_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate interval coverage by local energy day, including DST days."""
    grouped: dict[date, list[tuple[datetime, datetime, int]]] = defaultdict(list)
    latest_measurement: datetime | None = None
    for row in rows:
        interval = _interval_minutes(row.get("interval_minutes"))
        stamp = row.get("timestamp_utc")
        if not interval or interval <= 0 or not stamp:
            continue
        interval_end = _utc_datetime(str(stamp))
        interval_start = interval_end - timedelta(minutes=interval)
        local_day = interval_start.astimezone(PARIS).date()
        grouped[local_day].append((interval_start, interval_end, interval))
        latest_measurement = max(latest_measurement, interval_end) if latest_measurement else interval_end

    if not grouped:
        return {
            "days": {}, "complete_days": 0, "incomplete_days": [],
            "latest_measurement": None, "latest_complete_day": None,
        }

    first_day, last_day = min(grouped), max(grouped)
    day_results: dict[str, Any] = {}
    complete_dates: list[date] = []
    cursor = first_day
    while cursor <= last_day:
        expected_start = datetime.combine(cursor, datetime.min.time(), PARIS).astimezone(UTC)
        expected_end = datetime.combine(cursor + timedelta(days=1), datetime.min.time(), PARIS).astimezone(UTC)
        expected_minutes = int((expected_end - expected_start).total_seconds() / 60)
        intervals = sorted(grouped.get(cursor, []), key=lambda item: (item[0], item[1]))
        unique_intervals = list(dict.fromkeys(intervals))
        total_minutes = sum(item[2] for item in unique_intervals)
        continuous = bool(unique_intervals)
        if continuous:
            continuous = unique_intervals[0][0] == expected_start and unique_intervals[-1][1] == expected_end
            continuous = continuous and all(left[1] == right[0] for left, right in zip(unique_intervals, unique_intervals[1:]))
        steps = Counter(item[2] for item in unique_intervals)
        dominant_step = steps.most_common(1)[0][0] if steps else None
        expected_points = expected_minutes // dominant_step if dominant_step and expected_minutes % dominant_step == 0 else None
        complete = (
            continuous
            and total_minutes == expected_minutes
            and len(unique_intervals) == len(intervals)
            and (expected_points is None or len(unique_intervals) == expected_points)
        )
        if complete:
            complete_dates.append(cursor)
        day_results[cursor.isoformat()] = {
            "complete": complete,
            "points": len(unique_intervals),
            "minutes": total_minutes,
            "expected_minutes": expected_minutes,
            "step_minutes": dominant_step,
            "expected_points": expected_points,
            "continuous": continuous,
        }
        cursor += timedelta(days=1)

    incomplete = [day for day, item in day_results.items() if not item["complete"]]
    return {
        "days": day_results,
        "complete_days": len(complete_dates),
        "incomplete_days": incomplete,
        "latest_measurement": latest_measurement.isoformat(timespec="seconds").replace("+00:00", "Z") if latest_measurement else None,
        "latest_complete_day": max(complete_dates).isoformat() if complete_dates else None,
    }


def get_load_curve_quality(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if table not in ("load_consumption", "load_production"):
        raise ValueError("Table de courbe fine invalide.")
    rows = (dict(row) for row in conn.execute(
        f"SELECT timestamp_utc,timestamp_local,interval_minutes FROM {table} ORDER BY timestamp_utc"
    ))
    return load_curve_quality_rows(rows)


def _set_sync_state(
    conn: sqlite3.Connection,
    stream: str,
    status: str,
    start: date,
    end: date,
    *,
    last_data_at: str | None = None,
    error: LinkyError | None = None,
) -> None:
    conn.execute(
        """INSERT INTO sync_state
           (stream,last_success_at,last_data_at,last_request_start,last_request_end,status,error_code,error_message)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(stream) DO UPDATE SET
             last_success_at=COALESCE(excluded.last_success_at,sync_state.last_success_at),
             last_data_at=COALESCE(excluded.last_data_at,sync_state.last_data_at),
             last_request_start=excluded.last_request_start,last_request_end=excluded.last_request_end,
             status=excluded.status,error_code=excluded.error_code,error_message=excluded.error_message""",
        (stream, iso_now() if status in ("ok", "no_data") else None, last_data_at, start.isoformat(), end.isoformat(), status, error.code if error else None, str(error)[:300] if error else None),
    )


def _last_data_date(conn: sqlite3.Connection, table: str) -> date | None:
    column = "timestamp_local" if table.startswith("load_") else "day"
    row = conn.execute(f"SELECT MAX({column}) AS value FROM {table}").fetchone()
    if not row or not row["value"]:
        return None
    return date.fromisoformat(str(row["value"])[:10])


def _existing_key_count(conn: sqlite3.Connection, table: str, column: str, keys: set[str]) -> int:
    existing = 0
    values = list(keys)
    for offset in range(0, len(values), 800):
        batch = values[offset:offset + 800]
        placeholders = ",".join("?" for _ in batch)
        existing += conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})", batch).fetchone()[0]
    return existing


def _upsert_stream(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> tuple[str | None, int, int]:
    now = iso_now()
    key_column = "timestamp_utc" if table.startswith("load_") else "day"
    unique_keys = {str(r[key_column]) for r in rows}
    updated = _existing_key_count(conn, table, key_column, unique_keys) if unique_keys else 0
    added = len(unique_keys) - updated
    if table in ("daily_consumption", "daily_production"):
        conn.executemany(
            f"""INSERT INTO {table}(day,energy_wh,quality,source_updated_at) VALUES(?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET energy_wh=excluded.energy_wh,quality=excluded.quality,source_updated_at=excluded.source_updated_at""",
            [(r["day"], r["value"], r.get("quality", ""), now) for r in rows],
        )
        return max((r["day"] for r in rows), default=None), added, updated
    if table in ("load_consumption", "load_production"):
        conn.executemany(
            f"""INSERT INTO {table}(timestamp_utc,timestamp_local,value_w,interval_minutes,measure_type,source_updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(timestamp_utc) DO UPDATE SET
                timestamp_local=excluded.timestamp_local,value_w=excluded.value_w,interval_minutes=excluded.interval_minutes,
                measure_type=excluded.measure_type,source_updated_at=excluded.source_updated_at""",
            [(r["timestamp_utc"], r["timestamp_local"], r["value"], r.get("interval_minutes"), r.get("measure_type", ""), now) for r in rows],
        )
        return max((r["timestamp_local"] for r in rows), default=None), added, updated
    conn.executemany(
        """INSERT INTO daily_max_power(day,power_va,source_updated_at) VALUES(?,?,?)
           ON CONFLICT(day) DO UPDATE SET power_va=excluded.power_va,source_updated_at=excluded.source_updated_at""",
        [(r["day"], r["value"], now) for r in rows],
    )
    return max((r["day"] for r in rows), default=None), added, updated


def _sync_one(
    conn: sqlite3.Connection,
    client: MyElectricalDataClient | MockClient,
    stream: str,
    start: date,
    end: date,
    logger: logging.Logger,
) -> dict[str, Any]:
    endpoint, table = STREAMS[stream]
    parser = parse_load_curve if table.startswith("load_") else parse_max_power if table == "daily_max_power" else parse_daily
    max_days = 7 if table.startswith("load_") else 365
    rows: list[dict[str, Any]] = []
    try:
        chunks = load_curve_chunks(start, end, max_days, overlap_days=1) if table.startswith("load_") else date_chunks(start, end, max_days)
        for chunk_start, chunk_end in chunks:
            chunk_rows = parser(client.fetch(endpoint, chunk_start, chunk_end))
            rows.extend(chunk_rows)
            if table.startswith("load_"):
                first = min((row["timestamp_local"] for row in chunk_rows), default="—")
                last = max((row["timestamp_local"] for row in chunk_rows), default="—")
                logger.info(
                    "Bloc %s: demande %s -> %s (end exclusif), %d points, premier=%s, dernier=%s",
                    stream, chunk_start, chunk_end, len(chunk_rows), first, last,
                )
        with conn:
            last_data, added, updated = _upsert_stream(conn, table, rows)
            _set_sync_state(conn, stream, "ok" if rows else "no_data", start, end, last_data_at=last_data)
        unique_rows = len({row["timestamp_utc"] for row in rows}) if table.startswith("load_") else len({row.get("day") for row in rows})
        result = {"stream": stream, "status": "ok" if rows else "no_data", "rows": len(rows), "unique_rows": unique_rows, "added": added, "updated": updated}
        if table.startswith("load_"):
            quality = get_load_curve_quality(conn, table)
            result.update({
                "last_measurement": quality["latest_measurement"],
                "last_complete_day": quality["latest_complete_day"],
                "incomplete_days": quality["incomplete_days"],
            })
            logger.info(
                "Qualité %s: %d jours complets, incomplets=%s, dernière mesure=%s, dernière journée complète=%s",
                stream, quality["complete_days"], ",".join(quality["incomplete_days"]) or "aucun",
                quality["latest_measurement"] or "—", quality["latest_complete_day"] or "—",
            )
        logger.info("Synchro %s: %d reçues (%d uniques), %d ajoutées, %d mises à jour, du %s au %s", stream, len(rows), unique_rows, added, updated, start, end)
        return result
    except LinkyError as exc:
        with conn:
            _set_sync_state(conn, stream, exc.code, start, end, error=exc)
        logger.warning("Synchro %s interrompue: %s", stream, exc.code)
        return {"stream": stream, "status": exc.code, "rows": 0, "message": str(exc)}


def sync_stream_range(
    db_path: Path,
    client: MyElectricalDataClient | MockClient,
    stream: str,
    start: date,
    end: date,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Synchronize one explicit stream/range, used for targeted repairs."""
    if stream not in STREAMS:
        raise ConfigError("Flux Linky inconnu.")
    if end < start:
        raise ConfigError("Période Linky invalide.")
    conn = connect_db(db_path)
    try:
        return _sync_one(conn, client, stream, start, end, logger or logging.getLogger("cockpit.linky"))
    finally:
        conn.close()


def sync_linky(
    db_path: Path,
    client: MyElectricalDataClient | MockClient,
    *,
    history_start: date | None = None,
    today: date | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("cockpit.linky")
    conn = connect_db(db_path)
    effective_today = today or datetime.now(PARIS).date()
    end = effective_today - timedelta(days=1)
    if history_start and history_start > end:
        raise ConfigError("La date de début doit être antérieure à aujourd'hui.")
    try:
        access = client.valid_access()
    except LinkyError as exc:
        with conn:
            _set_sync_state(conn, "access", exc.code, history_start or end - timedelta(days=13), end, error=exc)
        conn.close()
        raise exc
    with conn:
        _set_sync_state(conn, "access", "ok", history_start or end - timedelta(days=13), end)
        for key in ("consent_expiration_date", "quota_reached", "quota_limit", "call_number"):
            if key in access:
                conn.execute("INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(access[key])))
    results = []
    for stream, (_, table) in STREAMS.items():
        last = _last_data_date(conn, table)
        if history_start:
            start = history_start
        elif last:
            if table.startswith("load_"):
                quality = get_load_curve_quality(conn, table)
                repair_day = min((date.fromisoformat(day) for day in quality["incomplete_days"]), default=None)
                anchor = repair_day or (date.fromisoformat(quality["latest_complete_day"]) if quality["latest_complete_day"] else last)
                start = anchor - timedelta(days=1)
            else:
                start = last - timedelta(days=3)
        else:
            start = end - timedelta(days=13)
        start = min(start, end)
        results.append(_sync_one(conn, client, stream, start, end, logger))
    conn.close()
    statuses = {r["status"] for r in results}
    overall = "ok" if statuses <= {"ok", "no_data"} else "partial"
    return {"status": overall, "synced_at": iso_now(), "streams": results}


def _metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for row in conn.execute("SELECT key,value FROM metadata"):
        try:
            values[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            values[row["key"]] = row["value"]
    return values


def get_status(db_path: Path, *, configured: bool, mock: bool = False) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "configured": configured, "mode": "mock" if mock else "real",
            "status": "demo" if mock else "not_configured" if not configured else "never_synced",
            "last_sync": None, "last_data": None, "last_daily_data": None, "summary": None, "streams": [], "load_curves": {},
        }
    conn = connect_db(db_path)
    states = [dict(row) for row in conn.execute("SELECT * FROM sync_state ORDER BY stream")]
    counts = {}
    last_values = []
    daily_last_values = []
    for _, table in STREAMS.values():
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        counts[table] = row["count"]
        last = _last_data_date(conn, table)
        if last:
            last_values.append(last.isoformat())
            if not table.startswith("load_"):
                daily_last_values.append(last.isoformat())
    last_sync = max((r["last_success_at"] for r in states if r["last_success_at"]), default=None)
    errors = [r for r in states if r["status"] not in ("ok", "no_data")]
    summary = get_daily_summary(conn)
    load_curves = {}
    for kind, table in (("consumption", "load_consumption"), ("production", "load_production")):
        quality = get_load_curve_quality(conn, table)
        load_curves[kind] = {
            "complete_days": quality["complete_days"],
            "incomplete_days": quality["incomplete_days"],
            "last_measurement": quality["latest_measurement"],
            "last_complete_day": quality["latest_complete_day"],
        }
    metadata = _metadata(conn)
    conn.close()
    status = "demo" if mock else "not_configured" if not configured else "attention" if errors else "up_to_date" if last_sync else "never_synced"
    return {
        "configured": configured,
        "mode": "mock" if mock else "real",
        "status": status,
        "last_sync": last_sync,
        "last_data": max(last_values, default=None),
        "last_daily_data": max(daily_last_values, default=None),
        "summary": summary,
        "load_curves": load_curves,
        "counts": counts,
        "streams": [{k: row[k] for k in ("stream", "status", "last_data_at", "error_code", "error_message")} for row in states],
        "consent_expiration_date": metadata.get("consent_expiration_date"),
        "quota": {"used": metadata.get("call_number"), "limit": metadata.get("quota_limit"), "reached": metadata.get("quota_reached")},
    }


def get_daily_summary(conn: sqlite3.Connection) -> dict[str, Any] | None:
    bounds = conn.execute(
        """SELECT MIN(day) AS first_day, MAX(day) AS last_day FROM (
             SELECT day FROM daily_consumption UNION SELECT day FROM daily_production
           )"""
    ).fetchone()
    if not bounds or not bounds["first_day"]:
        return None
    consumption = conn.execute("SELECT COALESCE(SUM(energy_wh),0) AS total FROM daily_consumption").fetchone()["total"]
    injection = conn.execute("SELECT COALESCE(SUM(energy_wh),0) AS total FROM daily_production").fetchone()["total"]
    consumption_bounds = conn.execute("SELECT MIN(day) AS first_day, MAX(day) AS last_day FROM daily_consumption").fetchone()
    injection_bounds = conn.execute("SELECT MIN(day) AS first_day, MAX(day) AS last_day FROM daily_production").fetchone()
    peak = conn.execute("SELECT MAX(power_va) AS value FROM daily_max_power").fetchone()["value"]
    return {
        "start": bounds["first_day"], "end": bounds["last_day"],
        "consumption_kwh": round(consumption / 1000, 1),
        "injection_kwh": round(injection / 1000, 1),
        "consumption_start": consumption_bounds["first_day"],
        "consumption_end": consumption_bounds["last_day"],
        "injection_start": injection_bounds["first_day"],
        "injection_end": injection_bounds["last_day"],
        "max_power_va": round(peak, 0) if peak is not None else None,
        "note": "Injection réseau mesurée par Linky; ce n'est pas la production photovoltaïque totale.",
    }


def get_daily_rows(db_path: Path, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    conn = connect_db(db_path)
    clauses, params = [], []
    if start:
        clauses.append("d.day >= ?")
        params.append(start.isoformat())
    if end:
        clauses.append("d.day <= ?")
        params.append(end.isoformat())
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"""WITH days AS (SELECT day FROM daily_consumption UNION SELECT day FROM daily_production)
            SELECT d.day, c.energy_wh AS consumption_wh, p.energy_wh AS injection_wh, m.power_va
            FROM days d LEFT JOIN daily_consumption c ON c.day=d.day
            LEFT JOIN daily_production p ON p.day=d.day LEFT JOIN daily_max_power m ON m.day=d.day
            {where} ORDER BY d.day""",
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_load_rows(db_path: Path, kind: str, start: date | None, end: date | None, limit: int = 4000) -> list[dict[str, Any]]:
    table = "load_production" if kind == "production" else "load_consumption"
    conn = connect_db(db_path)
    clauses, params = [], []
    if start:
        clauses.append("timestamp_local >= ?")
        params.append(start.isoformat())
    if end:
        clauses.append("timestamp_local < ?")
        params.append((end + timedelta(days=1)).isoformat())
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(limit, 20_000)))
    rows = conn.execute(
        f"SELECT timestamp_utc,timestamp_local,value_w,interval_minutes,measure_type FROM {table} {where} ORDER BY timestamp_utc LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def write_public_snapshot(db_path: Path, output_path: Path, *, configured: bool = True) -> None:
    status = get_status(db_path, configured=configured, mock=False)
    public = {k: status.get(k) for k in ("status", "last_sync", "last_data", "last_daily_data", "summary", "load_curves")}
    output_path.write_text("window.LINKY_DATA = " + json.dumps(public, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
