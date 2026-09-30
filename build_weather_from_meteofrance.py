#!/usr/bin/env python3
"""Build local Météo-France climate indicators for the solar dashboard.

The dashboard stays static: this script downloads public Météo-France daily
climatology files, filters the Albi station, computes yearly/monthly indicators,
and writes a small weather-data.js file consumed by site/app.js.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import io
import json
import math
import re
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


DAILY_DATASET_API = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "donnees-climatologiques-de-base-quotidiennes/"
)
STATION_DATASET_API = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "informations-sur-les-stations-meteo-france-metadonnees/"
)

DEFAULT_DEPARTMENT = "81"
DEFAULT_STATION = "81284001"
DEFAULT_FROM_YEAR = 2023
BASELINE_START = 1991
BASELINE_END = 2020

MONTH_NAMES = [
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
]

HOT_DAY_C = 30.0
VERY_HOT_DAY_C = 35.0
TROPICAL_NIGHT_C = 20.0
FROST_DAY_C = 0.0
HARD_FROST_DAY_C = -5.0
HEAVY_RAIN_MM = 20.0
RAIN_DAY_MM = 1.0
WIND_GUST_KMH = 60.0
HOT_SEQUENCE_MIN_DAYS = 3


@dataclass(frozen=True)
class WeatherRow:
    day: date
    year: int
    month: int
    rr_mm: float | None
    tn_c: float | None
    tx_c: float | None
    tm_c: float | None
    gust_kmh: float | None


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "cockpit-solaire-local/2.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(fetch_bytes(url).decode("utf-8"))


def maybe_gzip_decompress(raw: bytes, url: str) -> bytes:
    if url.lower().endswith(".gz"):
        return gzip.decompress(raw)
    return raw


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def safe_round(value: float | None, digits: int = 1) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return round(float(value), digits)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def parse_meteo_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def find_daily_resources(department: str) -> list[dict[str, str]]:
    data = fetch_json(DAILY_DATASET_API)
    resources = []
    pattern = re.compile(rf"departement_{re.escape(department)}_periode_(.+)_RR-T-Vent$")
    for resource in data.get("resources", []):
        title = str(resource.get("title") or "")
        match = pattern.search(title)
        if not match:
            continue
        period = match.group(1)
        if period == "avant-1949":
            continue
        resources.append(
            {
                "title": title,
                "url": str(resource.get("url") or ""),
                "period": period,
            }
        )

    if not resources:
        raise RuntimeError(f"Aucune ressource RR-T-Vent trouvée pour le département {department}.")

    def sort_key(item: dict[str, str]) -> tuple[int, str]:
        period = item["period"]
        if period.startswith("1950"):
            return (0, period)
        if "latest" in period or re.search(r"20\d{2}-20\d{2}", period):
            return (1, period)
        return (2, period)

    return sorted(resources, key=sort_key)


def find_station_metadata(station_id: str) -> dict[str, Any]:
    data = fetch_json(STATION_DATASET_API)
    csv_resources = [item for item in data.get("resources", []) if str(item.get("format", "")).lower() == "csv"]
    if not csv_resources:
        raise RuntimeError("Ressource CSV des stations Météo-France introuvable.")

    url = str(csv_resources[0]["url"])
    text = fetch_bytes(url).decode("utf-8-sig")
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("id") == station_id:
            return {
                "id": row.get("id"),
                "name": row.get("name"),
                "long_name": row.get("long_name") or row.get("name"),
                "named_place": row.get("named_place"),
                "lat": to_float(row.get("lat")),
                "lon": to_float(row.get("lon")),
                "alt_m": to_float(row.get("alt")),
                "start_date": row.get("start_date") or None,
                "end_date": row.get("end_date") or None,
                "is_open": str(row.get("is_open", "")).lower() == "true",
                "is_daily": str(row.get("is_daily", "")).lower() == "true",
                "source_url": url,
            }
    raise RuntimeError(f"Station Météo-France {station_id} introuvable.")


def read_station_rows(resources: list[dict[str, str]], station_id: str, min_year: int) -> list[WeatherRow]:
    rows: list[WeatherRow] = []
    for resource in resources:
        if not resource["url"]:
            continue
        raw = maybe_gzip_decompress(fetch_bytes(resource["url"]), resource["url"])
        text = raw.decode("utf-8-sig", errors="replace")
        for item in csv.DictReader(io.StringIO(text), delimiter=";"):
            if item.get("NUM_POSTE") != station_id:
                continue
            day = parse_meteo_date(item["AAAAMMJJ"])
            if day.year < min_year:
                continue
            gust_ms = to_float(item.get("FXI"))
            rows.append(
                WeatherRow(
                    day=day,
                    year=day.year,
                    month=day.month,
                    rr_mm=to_float(item.get("RR")),
                    tn_c=to_float(item.get("TN")),
                    tx_c=to_float(item.get("TX")),
                    tm_c=to_float(item.get("TM")),
                    gust_kmh=gust_ms * 3.6 if gust_ms is not None else None,
                )
            )

    rows.sort(key=lambda item: item.day)
    # One station should have one row per day, but this keeps the output stable
    # if a source file ever contains duplicates.
    deduped: dict[date, WeatherRow] = {}
    for row in rows:
        deduped[row.day] = row
    return [deduped[key] for key in sorted(deduped)]


def longest_streak(rows: list[WeatherRow], predicate: Any) -> dict[str, Any]:
    best_start: date | None = None
    best_end: date | None = None
    best_count = 0
    start: date | None = None
    previous: date | None = None
    count = 0

    for row in sorted(rows, key=lambda item: item.day):
        contiguous = previous is not None and (row.day - previous).days == 1
        matches = predicate(row)
        if matches:
            if start is None or not contiguous:
                start = row.day
                count = 0
            count += 1
            if count > best_count:
                best_count = count
                best_start = start
                best_end = row.day
        else:
            start = None
            count = 0
        previous = row.day

    return {
        "days": best_count,
        "start": best_start.isoformat() if best_start else None,
        "end": best_end.isoformat() if best_end else None,
    }


def hot_sequences(rows: list[WeatherRow]) -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    current: list[WeatherRow] = []
    previous: date | None = None

    def flush() -> None:
        if len(current) < HOT_SEQUENCE_MIN_DAYS:
            return
        tx_values = [row.tx_c for row in current if row.tx_c is not None]
        episodes.append(
            {
                "start": current[0].day.isoformat(),
                "end": current[-1].day.isoformat(),
                "days": len(current),
                "max_tx_c": safe_round(max(tx_values), 1) if tx_values else None,
            }
        )

    for row in sorted(rows, key=lambda item: item.day):
        contiguous = previous is not None and (row.day - previous).days == 1
        is_hot = row.tx_c is not None and row.tx_c >= HOT_DAY_C
        if is_hot:
            if current and not contiguous:
                flush()
                current = []
            current.append(row)
        else:
            flush()
            current = []
        previous = row.day
    flush()

    return {
        "episodes": episodes,
        "episode_count": len(episodes),
        "days": sum(item["days"] for item in episodes),
        "longest_days": max((item["days"] for item in episodes), default=0),
    }


def pick_extreme(rows: list[WeatherRow], key: str, direction: str) -> dict[str, Any]:
    valid = [row for row in rows if getattr(row, key) is not None]
    if not valid:
        return {"date": None, "value": None}
    selected = max(valid, key=lambda row: getattr(row, key)) if direction == "max" else min(valid, key=lambda row: getattr(row, key))
    return {"date": selected.day.isoformat(), "value": safe_round(getattr(selected, key), 1)}


def build_metrics(rows: list[WeatherRow], year: int | None = None, month: int | None = None) -> dict[str, Any]:
    rows = sorted(rows, key=lambda item: item.day)
    tx_values = [row.tx_c for row in rows if row.tx_c is not None]
    tn_values = [row.tn_c for row in rows if row.tn_c is not None]
    tm_values = [row.tm_c for row in rows if row.tm_c is not None]
    rr_values = [row.rr_mm for row in rows if row.rr_mm is not None]
    gust_values = [row.gust_kmh for row in rows if row.gust_kmh is not None]
    wettest = pick_extreme(rows, "rr_mm", "max")
    hottest = pick_extreme(rows, "tx_c", "max")
    coldest = pick_extreme(rows, "tn_c", "min")
    gustiest = pick_extreme(rows, "gust_kmh", "max")
    hot_seq = hot_sequences(rows)
    dry_spell = longest_streak(rows, lambda row: row.rr_mm is not None and row.rr_mm < RAIN_DAY_MM)

    expected_days = days_in_year(year) if year else len(rows)
    filled_days = len({row.day for row in rows})

    return {
        "year": year,
        "month": month,
        "label": MONTH_NAMES[month - 1] if month else None,
        "filled_days": filled_days,
        "expected_days": expected_days,
        "coverage_percent": safe_round(filled_days / expected_days * 100 if expected_days else 0.0, 1),
        "avg_tx_c": safe_round(mean(tx_values), 1),
        "avg_tn_c": safe_round(mean(tn_values), 1),
        "avg_tm_c": safe_round(mean(tm_values), 1),
        "max_tx_c": hottest["value"],
        "max_tx_date": hottest["date"],
        "min_tn_c": coldest["value"],
        "min_tn_date": coldest["date"],
        "hot_days_30": sum(1 for value in tx_values if value >= HOT_DAY_C),
        "very_hot_days_35": sum(1 for value in tx_values if value >= VERY_HOT_DAY_C),
        "tropical_nights_20": sum(1 for value in tn_values if value >= TROPICAL_NIGHT_C),
        "frost_days": sum(1 for value in tn_values if value <= FROST_DAY_C),
        "hard_frost_days": sum(1 for value in tn_values if value <= HARD_FROST_DAY_C),
        "ice_days": sum(1 for row in rows if row.tx_c is not None and row.tx_c <= FROST_DAY_C),
        "rain_total_mm": safe_round(sum(rr_values), 1),
        "rain_days_1mm": sum(1 for value in rr_values if value >= RAIN_DAY_MM),
        "heavy_rain_days_20mm": sum(1 for value in rr_values if value >= HEAVY_RAIN_MM),
        "wettest_day_mm": wettest["value"],
        "wettest_day_date": wettest["date"],
        "longest_dry_spell_days": dry_spell["days"],
        "longest_dry_spell_start": dry_spell["start"],
        "longest_dry_spell_end": dry_spell["end"],
        "wind_gust_max_kmh": safe_round(max(gust_values), 0) if gust_values else None,
        "wind_gust_max_date": gustiest["date"],
        "windy_days_60kmh": sum(1 for value in gust_values if value >= WIND_GUST_KMH),
        "estimated_hot_sequence_days": hot_seq["days"],
        "estimated_hot_sequence_episodes": hot_seq["episode_count"],
        "longest_hot_sequence_days": hot_seq["longest_days"],
        "hot_sequences": hot_seq["episodes"][:5],
    }


def average_normals(year_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "avg_tx_c",
        "avg_tn_c",
        "avg_tm_c",
        "hot_days_30",
        "very_hot_days_35",
        "tropical_nights_20",
        "frost_days",
        "hard_frost_days",
        "ice_days",
        "rain_total_mm",
        "rain_days_1mm",
        "heavy_rain_days_20mm",
        "longest_dry_spell_days",
        "windy_days_60kmh",
        "estimated_hot_sequence_days",
    ]
    normals: dict[str, Any] = {}
    for key in keys:
        values = [float(item[key]) for item in year_metrics if item.get(key) is not None]
        normals[key] = safe_round(mean(values), 1) if values else None
    return normals


def add_anomalies(metrics: dict[str, Any], normals: dict[str, Any]) -> None:
    pairs = {
        "avg_tx_c": "avg_tx_delta_c",
        "hot_days_30": "hot_days_30_delta",
        "very_hot_days_35": "very_hot_days_35_delta",
        "frost_days": "frost_days_delta",
        "rain_total_mm": "rain_total_delta_mm",
        "rain_days_1mm": "rain_days_1mm_delta",
        "heavy_rain_days_20mm": "heavy_rain_days_20mm_delta",
        "longest_dry_spell_days": "longest_dry_spell_delta_days",
    }
    for source_key, output_key in pairs.items():
        value = metrics.get(source_key)
        normal = normals.get(source_key)
        metrics[output_key] = safe_round(float(value) - float(normal), 1) if value is not None and normal is not None else None

    rain = metrics.get("rain_total_mm")
    normal_rain = normals.get("rain_total_mm")
    metrics["rain_total_delta_percent"] = (
        safe_round((float(rain) - float(normal_rain)) / float(normal_rain) * 100, 1)
        if rain is not None and normal_rain
        else None
    )


def notable_events(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if metrics.get("max_tx_c") is not None:
        events.append(
            {
                "type": "heat",
                "label": "Pic de chaleur",
                "value": f"{metrics['max_tx_c']:.1f} °C",
                "date": metrics.get("max_tx_date"),
            }
        )
    if metrics.get("min_tn_c") is not None:
        events.append(
            {
                "type": "cold",
                "label": "Nuit la plus froide",
                "value": f"{metrics['min_tn_c']:.1f} °C",
                "date": metrics.get("min_tn_date"),
            }
        )
    if metrics.get("wettest_day_mm") is not None:
        events.append(
            {
                "type": "rain",
                "label": "Pluie la plus forte",
                "value": f"{metrics['wettest_day_mm']:.1f} mm",
                "date": metrics.get("wettest_day_date"),
            }
        )
    if metrics.get("longest_dry_spell_days"):
        events.append(
            {
                "type": "dry",
                "label": "Plus longue période sèche",
                "value": f"{metrics['longest_dry_spell_days']} jours",
                "date": metrics.get("longest_dry_spell_start"),
                "end_date": metrics.get("longest_dry_spell_end"),
            }
        )
    if metrics.get("wind_gust_max_kmh") is not None:
        events.append(
            {
                "type": "wind",
                "label": "Rafale maximale",
                "value": f"{metrics['wind_gust_max_kmh']:.0f} km/h",
                "date": metrics.get("wind_gust_max_date"),
            }
        )
    return events


def build_weather_data(args: argparse.Namespace) -> dict[str, Any]:
    min_year = min(args.from_year, args.baseline_start)
    resources = find_daily_resources(args.department)
    station = find_station_metadata(args.station)
    rows = read_station_rows(resources, args.station, min_year)
    if not rows:
        raise RuntimeError(f"Aucune donnée quotidienne trouvée pour la station {args.station}.")

    by_year: dict[int, list[WeatherRow]] = defaultdict(list)
    for row in rows:
        by_year[row.year].append(row)

    baseline_metrics = []
    for year in range(args.baseline_start, args.baseline_end + 1):
        year_rows = by_year.get(year, [])
        metrics = build_metrics(year_rows, year=year)
        if metrics["coverage_percent"] and metrics["coverage_percent"] >= 95:
            baseline_metrics.append(metrics)
    normals = average_normals(baseline_metrics)

    years = []
    latest_year = max(by_year)
    for year in sorted(item for item in by_year if item >= args.from_year):
        year_rows = by_year[year]
        metrics = build_metrics(year_rows, year=year)
        add_anomalies(metrics, normals)
        metrics["status"] = "En cours" if year == latest_year and metrics["coverage_percent"] < 98 else "Année complète"
        metrics["months"] = [
            build_metrics([row for row in year_rows if row.month == month], year=None, month=month)
            for month in range(1, 13)
        ]
        metrics["events"] = notable_events(metrics)
        years.append(metrics)

    first_date = min(row.day for row in rows if row.year >= args.from_year)
    latest_date = max(row.day for row in rows if row.year >= args.from_year)

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dataset": "Météo-France - Données climatologiques de base quotidiennes",
            "dataset_url": "https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes",
            "station_dataset_url": "https://www.data.gouv.fr/datasets/informations-sur-les-stations-meteo-france-metadonnees",
            "department": args.department,
            "station_id": args.station,
            "first_date": first_date.isoformat(),
            "latest_date": latest_date.isoformat(),
            "baseline_period": f"{args.baseline_start}-{args.baseline_end}",
            "source_resources": resources,
            "thresholds": {
                "hot_day_c": HOT_DAY_C,
                "very_hot_day_c": VERY_HOT_DAY_C,
                "tropical_night_c": TROPICAL_NIGHT_C,
                "frost_day_c": FROST_DAY_C,
                "hard_frost_day_c": HARD_FROST_DAY_C,
                "rain_day_mm": RAIN_DAY_MM,
                "heavy_rain_mm": HEAVY_RAIN_MM,
                "wind_gust_kmh": WIND_GUST_KMH,
                "estimated_hot_sequence_min_days": HOT_SEQUENCE_MIN_DAYS,
            },
            "note": "Les séquences chaudes sont un indicateur local estimé, pas une déclaration officielle de canicule.",
        },
        "station": station,
        "normals": {
            "period": f"{args.baseline_start}-{args.baseline_end}",
            "year_count": len(baseline_metrics),
            "annual": normals,
        },
        "years": years,
    }


def write_weather_data(data: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    output_path.write_text("window.SOLAR_WEATHER_DATA = " + payload + ";\n", encoding="utf-8")
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Météo-France weather data for the dashboard.")
    parser.add_argument("--department", default=DEFAULT_DEPARTMENT, help="French department code.")
    parser.add_argument("--station", default=DEFAULT_STATION, help="Météo-France station id.")
    parser.add_argument("--from-year", type=int, default=DEFAULT_FROM_YEAR, help="First dashboard year to export.")
    parser.add_argument("--baseline-start", type=int, default=BASELINE_START, help="First year for climatological baseline.")
    parser.add_argument("--baseline-end", type=int, default=BASELINE_END, help="Last year for climatological baseline.")
    parser.add_argument("--output", default=None, help="Output JS path. Defaults to site/weather-data.js.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    project_dir = Path(__file__).resolve().parents[1]
    output_path = Path(args.output) if args.output else project_dir / "site" / "weather-data.js"
    if not output_path.is_absolute():
        output_path = (project_dir / output_path).resolve()

    try:
        weather_data = build_weather_data(args)
        output = write_weather_data(weather_data, output_path)
    except Exception as exc:
        print(f"Erreur pendant la génération météo: {exc}")
        return 1

    station = weather_data["station"]
    print(f"Météo-France mise à jour: {output}")
    print(f"Station: {station['name']} ({station['id']})")
    print(f"Dernière donnée météo: {weather_data['meta']['latest_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
