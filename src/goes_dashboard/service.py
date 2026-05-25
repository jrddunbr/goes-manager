"""Serve a recent-EMWIN dashboard with station markers."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import io
import re
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from statistics import mean
from typing import Iterable

from flask import Flask, abort, jsonify, render_template, request, send_file
from PIL import Image

UTC = timezone.utc
FILENAME_RE = re.compile(
    r"^(?P<queue>[AZ])_"
    r"(?P<header>[A-Z0-9]{6})(?P<origin>[A-Z0-9]{4})(?P<issued>\d{6})_"
    r"C_(?P<source>[A-Z0-9]{4})_"
    r"(?P<receipt>\d{14})_"
    r"(?P<message_id>[^-]+)-(?P<priority>\d)-(?P<awips>[^.]+)"
    r"(?P<suffix>\.[A-Za-z0-9]+)$"
)
LAT_LON_RE = re.compile(r"LAT\.\.\.LON\s+(?P<body>.+?)(?:\n\n|TIME\.\.\.|[&$]{2})", re.DOTALL)
COORD_TOKEN_RE = re.compile(r"\b\d{4,5}\b")
DEFAULT_WINDOW_HOURS = 6
DEFAULT_EMWIN_ROOT = Path("EMWIN")
RADAR_COMPOSITE_KEY_HEIGHT = 24
RADAR_COMPOSITE_GRID = {
    "alaska": (0, 0),
    "northwest": (1, 0),
    "north-central": (2, 0),
    "upper-mississippi": (3, 0),
    "great-lakes": (4, 0),
    "northeast": (5, 0),
    "hawaii": (0, 1),
    "southwest": (1, 1),
    "south-central": (2, 1),
    "southern-plains": (3, 1),
    "lower-mississippi": (4, 1),
    "southeast": (5, 1),
    "puerto-rico": (5, 2),
    "guam": (5, 3),
}


@dataclass(frozen=True)
class StationLocation:
    code: str
    name: str
    city: str
    subdivision: str
    country: str
    latitude: float
    longitude: float
    source: str


@dataclass(frozen=True)
class EmwinProduct:
    path: str
    relative_path: str
    filename: str
    category: str
    awips_id: str
    family: str
    originator: str
    source: str
    receipt_time: datetime
    issued_code: str
    title: str
    summary: str
    extension: str
    station_codes: tuple[str, ...] = ()
    lat_lon_centroid: tuple[float, float] | None = None
    detail_sections: tuple[tuple[str, str], ...] = ()
    product_type: str = "EMWIN Product"
    image_category: str = ""
    image_slot: str = ""
    related_reports: tuple[tuple[str, str, str], ...] = ()
    station_views: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class StationSummary:
    code: str
    name: str
    city: str
    subdivision: str
    country: str
    latitude: float
    longitude: float
    source: str
    latest_seen: datetime
    products: list[dict[str, object]] = field(default_factory=list)
    marker_kind: str = "text"
    weather_summary: str = ""
    weather_time: datetime | None = None
    weather_details: dict[str, object] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


@lru_cache(maxsize=1)
def load_airport_index() -> dict[str, StationLocation]:
    """Load the vendored airport reference dataset keyed by ICAO and FAA LID."""

    rows: dict[str, StationLocation] = {}
    with resources.files("goes_dashboard.data").joinpath("airports.csv").open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                latitude = float(row["lat"])
                longitude = float(row["lon"])
            except (TypeError, ValueError):
                continue
            location = StationLocation(
                code=row["icao"],
                name=row["name"],
                city=row["city"],
                subdivision=row["subd"],
                country=row["country"],
                latitude=latitude,
                longitude=longitude,
                source="airportsdata",
            )
            if row["icao"]:
                rows[row["icao"].upper()] = location
            lid = (row.get("lid") or "").upper()
            if lid:
                rows[lid] = StationLocation(
                    code=lid,
                    name=row["name"],
                    city=row["city"],
                    subdivision=row["subd"],
                    country=row["country"],
                    latitude=latitude,
                    longitude=longitude,
                    source="airportsdata-lid",
                )
    return rows


def parse_filename(path: Path) -> EmwinProduct | None:
    match = FILENAME_RE.match(path.name)
    if not match:
        return None

    receipt_time = datetime.strptime(match.group("receipt"), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    awips_id = match.group("awips")
    family = awips_id[:3]
    category = "graphic" if match.group("queue") == "Z" else "text"
    return EmwinProduct(
        path=str(path),
        relative_path=str(path),
        filename=path.name,
        category=category,
        awips_id=awips_id,
        family=family,
        originator=match.group("origin"),
        source=match.group("source"),
        receipt_time=receipt_time,
        issued_code=match.group("issued"),
        title=awips_id,
        summary="",
        extension=match.group("suffix").lstrip(".").lower(),
    )


def make_feed_id(filename: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", filename).strip("-").lower()
    return f"product-{slug or 'item'}"


def parse_lat_lon_centroid(text: str) -> tuple[float, float] | None:
    match = LAT_LON_RE.search(text)
    if not match:
        return None

    coords = []
    tokens = COORD_TOKEN_RE.findall(match.group("body"))
    for index in range(0, len(tokens) - 1, 2):
        lat_token = tokens[index]
        lon_token = tokens[index + 1]
        coords.append((_decode_lat_token(lat_token), _decode_lon_token(lon_token)))

    if not coords:
        return None

    return (round(mean(lat for lat, _ in coords), 4), round(mean(lon for _, lon in coords), 4))


def _decode_lat_token(token: str) -> float:
    return float(token[:-2] + "." + token[-2:])


def _decode_lon_token(token: str) -> float:
    return -float(token[:-2] + "." + token[-2:])


def summarise_text(text: str, awips_id: str) -> tuple[str, str]:
    lines = [line.strip(" \r") for line in text.splitlines()]
    meaningful = [line for line in lines if line]
    if not meaningful:
        return awips_id, "No bulletin text available."

    title = meaningful[1] if len(meaningful) > 1 else meaningful[0]
    if title == awips_id and len(meaningful) > 2:
        title = meaningful[2]

    summary_lines: list[str] = []
    for line in meaningful[2:10]:
        if line == awips_id:
            continue
        summary_lines.append(line)
        if len(" ".join(summary_lines)) >= 220:
            break

    summary = " ".join(summary_lines).strip() or meaningful[0]
    return title[:120], summary[:280]


def split_nonempty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


PRODUCT_TYPE_LABELS = {
    "AFD": "Forecast Discussion",
    "ZFP": "Zone Forecast",
    "PFM": "Point Forecast Matrix",
    "RWR": "Regional Weather Roundup",
    "RRM": "Rainfall Report",
    "RVA": "River Statement",
    "SFT": "Tabular Forecast",
    "TAF": "Terminal Aerodrome Forecast",
    "MET": "Meteorological Observation",
    "SAH": "Hourly Observation",
    "FWF": "Fire Weather Forecast",
    "CWF": "Coastal Waters Forecast",
    "QPS": "Quantitative Precipitation Summary",
    "IMG": "Graphic Bulletin",
    "RAD": "Radar Graphic",
    "G02": "Satellite Graphic",
    "G16": "Satellite Graphic",
    "G10": "Satellite Graphic",
}

FAMILY_LABELS = {
    "SAH": "Hourly Observations",
    "RWR": "Regional Weather Roundups",
    "MIS": "Marine and Misc Summaries",
    "TAF": "Terminal Forecasts",
    "CLI": "Climate Reports",
    "SVS": "Severe Weather Statements",
    "OBS": "Surface Observations",
    "RRM": "Rainfall Reports",
    "LSR": "Local Storm Reports",
    "AFD": "Forecast Discussions",
    "ZFP": "Zone Forecasts",
    "PFM": "Point Forecast Matrices",
}


WMO_RE = re.compile(r"^[A-Z]{4,6}\d{2}\s+[A-Z]{4}\s+\d{6}$")
REPORT_LINE_RE = re.compile(r"^[A-Z0-9]{3,4}\s+\d{6}Z\b")
TAF_LINE_RE = re.compile(r"^(?:TAF\s+)?(?P<code>[A-Z0-9]{3,4})\s+\d{6}Z\b")
VISIBILITY_RE = re.compile(r"^(?P<value>P?\d+(?:/\d+)?)SM$")
ALTIMETER_RE = re.compile(r"^A(?P<value>\d{4})$")
TEMP_DEW_RE = re.compile(r"^(?P<temp>M?\d{2})/(?P<dew>M?\d{2})$")
WIND_RE = re.compile(r"^(?P<direction>\d{3}|VRB)(?P<speed>\d{2,3})(?:G(?P<gust>\d{2,3}))?KT$")

SKY_COVER_LABELS = {
    "CLR": "clear",
    "SKC": "clear",
    "FEW": "few clouds",
    "SCT": "scattered clouds",
    "BKN": "broken clouds",
    "OVC": "overcast",
    "VV": "vertical visibility",
}

WEATHER_CODES = {
    "TSRA": "thunderstorms with rain",
    "-TSRA": "light thunderstorms with rain",
    "+TSRA": "heavy thunderstorms with rain",
    "SHRA": "rain showers",
    "-SHRA": "light rain showers",
    "+SHRA": "heavy rain showers",
    "RA": "rain",
    "-RA": "light rain",
    "+RA": "heavy rain",
    "DZ": "drizzle",
    "BR": "mist",
    "FG": "fog",
    "HZ": "haze",
    "SN": "snow",
}

GRAPHIC_CATEGORY_LABELS = {
    "radar-regions": "Regional Radar",
    "satellite": "Satellite",
    "forecast-alerts": "Forecasts and Alerts",
    "oceanic": "Oceanic and Pacific",
    "other": "Other Images",
}

GRAPHIC_TITLE_OVERRIDES = {
    "RADPACNW": "Pacific Northwest radar mosaic",
    "RADPACSW": "Pacific Southwest radar mosaic",
    "RADRCKNT": "Northern Rockies radar mosaic",
    "RADRCKST": "Southern Rockies radar mosaic",
    "RADSMSVY": "South Mississippi Valley radar mosaic",
    "RADUMSVY": "Upper Mississippi Valley radar mosaic",
    "RADGRTLK": "Great Lakes radar mosaic",
    "RADNTHES": "Northeast radar mosaic",
    "RADSTHES": "Southeast radar mosaic",
    "RADSTHPL": "Southern Plains radar mosaic",
    "RADREFUS": "National radar reflectivity",
    "RADALLAK": "Alaska radar mosaic",
    "RADALLHI": "Hawaii radar mosaic",
    "RADALLPR": "Puerto Rico radar mosaic",
    "RADALLGU": "Guam radar mosaic",
    "G16CIRUS": "GOES-16 continental infrared",
    "G10CIRUS": "GOES-10 infrared overview",
    "G10FDIUS": "Fire danger imagery",
    "G02HURUS": "Atlantic hurricane satellite view",
    "IMGSJUPR": "Puerto Rico satellite image",
    "IMGWWAUS": "US watches, warnings, and advisories",
    "GPHJ88US": "National weather graphic",
}

GRAPHIC_SLOT_MAP = {
    "RADPACNW": "northwest",
    "RADPACSW": "southwest",
    "RADRCKNT": "north-central",
    "RADRCKST": "south-central",
    "RADSTHPL": "southern-plains",
    "RADSMSVY": "lower-mississippi",
    "RADUMSVY": "upper-mississippi",
    "RADGRTLK": "great-lakes",
    "RADNTHES": "northeast",
    "RADSTHES": "southeast",
    "RADREFUS": "national-below",
    "RADALLAK": "alaska",
    "RADALLHI": "hawaii",
    "RADALLPR": "puerto-rico",
    "RADALLGU": "guam",
}


def classify_product_type(product: EmwinProduct) -> str:
    if product.category == "graphic":
        if product.awips_id.startswith("RAD"):
            return "Radar Graphic"
        if product.awips_id.startswith(("G02", "G16", "G10", "IMG")):
            return "Satellite Graphic"
        return "Graphic Image"

    if len(product.awips_id) >= 3:
        return PRODUCT_TYPE_LABELS.get(product.awips_id[:3], PRODUCT_TYPE_LABELS.get(product.family, "Text Bulletin"))
    return "Text Bulletin"


def classify_graphic_category(product: EmwinProduct) -> str:
    if product.awips_id.startswith("RAD"):
        return "radar-regions"
    if product.awips_id.startswith(("G16", "G10", "G02", "GMS", "IND", "NPI")):
        return "satellite"
    if product.awips_id.startswith(("IMG", "GPH")):
        return "forecast-alerts"
    return "other"


def describe_graphic_product(product: EmwinProduct) -> tuple[str, str, str, str]:
    image_category = classify_graphic_category(product)
    title = GRAPHIC_TITLE_OVERRIDES.get(product.awips_id, product.awips_id)
    summary = f"{GRAPHIC_CATEGORY_LABELS.get(image_category, 'Image')} in {product.extension.upper()} format."
    image_slot = GRAPHIC_SLOT_MAP.get(product.awips_id, "")
    return title, summary, image_category, image_slot


def _decode_signed_temperature(token: str) -> str:
    value = int(token[1:]) if token.startswith("M") else int(token)
    if token.startswith("M"):
        value = -value
    return f"{value} C"


def _c_to_f_text(token: str) -> str:
    value = int(token[1:]) if token.startswith("M") else int(token)
    if token.startswith("M"):
        value = -value
    fahrenheit = (value * 9 / 5) + 32
    return f"{round(fahrenheit)} F"


def _friendly_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone(UTC).strftime("%b %-d, %Y %H:%M UTC")


def _friendly_zulu_time(token: str) -> str:
    if len(token) != 7 or not token.endswith("Z"):
        return token
    return f"{token[:2]}:{token[2:4]} UTC on day {token[4:6]}"


def _friendly_taf_window(token: str) -> str:
    if len(token) == 9 and "/" in token:
        start, end = token.split("/", 1)
        if len(start) == 4 and len(end) == 4:
            return f"day {start[:2]} {start[2:]}Z to day {end[:2]} {end[2:]}Z"
    return token


def _friendly_fm_time(token: str) -> str:
    if len(token) == 6 and token.isdigit():
        return f"day {token[:2]} at {token[2:4]}:{token[4:]} UTC"
    return token


def decode_metar_line(line: str) -> dict[str, str] | None:
    parts = line.replace("=", "").split()
    if len(parts) < 3 or not REPORT_LINE_RE.match(" ".join(parts[:2])):
        return None

    wind = ""
    wind_degrees = ""
    visibility = ""
    weather: list[str] = []
    sky: list[str] = []
    temperature = ""
    altimeter = ""
    temperature_f = ""
    dew_point_f = ""

    for token in parts[2:]:
        wind_match = WIND_RE.match(token)
        if wind_match:
            direction = wind_match.group("direction")
            speed = int(wind_match.group("speed"))
            gust = wind_match.group("gust")
            direction_label = "variable" if direction == "VRB" else f"{direction} deg"
            wind_degrees = "" if direction == "VRB" else direction
            wind = f"{direction_label} at {speed} kt"
            if gust:
                wind += f", gusting {int(gust)} kt"
            continue

        visibility_match = VISIBILITY_RE.match(token)
        if visibility_match:
            visibility = f"{visibility_match.group('value')} sm visibility"
            continue

        if token in WEATHER_CODES:
            weather.append(WEATHER_CODES[token])
            continue

        if token[:3] in SKY_COVER_LABELS:
            cover = SKY_COVER_LABELS[token[:3]]
            if token[3:].isdigit():
                sky.append(f"{cover} at {int(token[3:]) * 100} ft")
            else:
                sky.append(cover)
            continue

        temp_match = TEMP_DEW_RE.match(token)
        if temp_match:
            temperature = (
                f"{_decode_signed_temperature(temp_match.group('temp'))} / "
                f"{_decode_signed_temperature(temp_match.group('dew'))}"
            )
            temperature_f = _c_to_f_text(temp_match.group("temp"))
            dew_point_f = _c_to_f_text(temp_match.group("dew"))
            continue

        altimeter_match = ALTIMETER_RE.match(token)
        if altimeter_match:
            value = altimeter_match.group("value")
            altimeter = f"{value[:2]}.{value[2:]} inHg"

    return {
        "station": parts[0],
        "time": parts[1],
        "summary": "; ".join(
            segment for segment in [wind, visibility, ", ".join(weather), ", ".join(sky), temperature, altimeter] if segment
        ) or "Observation available.",
        "temperature_detail": temperature,
        "temperature_f": temperature_f,
        "dew_point_f": dew_point_f,
        "wind_text": wind,
        "wind_degrees": wind_degrees,
        "visibility_text": visibility,
        "weather_text": ", ".join(weather),
        "sky_text": ", ".join(sky),
        "pressure_text": altimeter,
    }


def decode_taf_tokens(tokens: list[str]) -> str:
    parts: list[str] = []
    for token in tokens:
        wind_match = WIND_RE.match(token)
        if wind_match:
            direction = wind_match.group("direction")
            speed = int(wind_match.group("speed"))
            gust = wind_match.group("gust")
            direction_label = "variable" if direction == "VRB" else f"{direction} degrees"
            segment = f"winds {direction_label} at {speed} kt"
            if gust:
                segment += f", gusting {int(gust)} kt"
            parts.append(segment)
            continue

        visibility_match = VISIBILITY_RE.match(token)
        if visibility_match:
            parts.append(f"visibility {visibility_match.group('value')} statute miles")
            continue

        if token in WEATHER_CODES:
            parts.append(WEATHER_CODES[token])
            continue

        if token[:3] in SKY_COVER_LABELS:
            cover = SKY_COVER_LABELS[token[:3]]
            if token[3:].isdigit():
                parts.append(f"{cover} at {int(token[3:]) * 100} ft")
            else:
                parts.append(cover)
            continue

        if token.startswith("WS"):
            parts.append(f"low-level wind shear {token[2:]}")
            continue

    return ", ".join(parts) if parts else "forecast conditions listed in coded form"


def decode_taf_change_group(group: str) -> str:
    tokens = group.split()
    if not tokens:
        return ""
    lead = tokens[0]
    if lead.startswith("FM"):
        remainder = decode_taf_tokens(tokens[1:])
        return f"From {_friendly_fm_time(lead[2:])}, expect {remainder}"
    if lead == "TEMPO" and len(tokens) > 1:
        remainder = decode_taf_tokens(tokens[2:])
        return f"Temporarily during {_friendly_taf_window(tokens[1])}, expect {remainder}"
    if lead.startswith("PROB") and len(tokens) > 1:
        remainder = decode_taf_tokens(tokens[2:])
        return f"{lead} chance during {_friendly_taf_window(tokens[1])}, expect {remainder}"
    remainder = decode_taf_tokens(tokens[1:])
    return f"{lead}: {remainder}"


def decode_taf_block(block_lines: list[str]) -> dict[str, str] | None:
    if not block_lines:
        return None

    parts = " ".join(line.replace("=", "").strip() for line in block_lines).split()
    if len(parts) < 4:
        return None

    station = parts[0]
    issued = parts[1]
    valid = parts[2]
    base_conditions: list[str] = []
    changes: list[str] = []
    current_change: list[str] = []

    for token in parts[3:]:
        if token.startswith(("FM", "TEMPO", "PROB")):
            if current_change:
                changes.append(" ".join(current_change))
            current_change = [token]
        elif current_change:
            current_change.append(token)
        else:
            base_conditions.append(token)
    if current_change:
        changes.append(" ".join(current_change))

    return {
        "station": station,
        "issued": issued,
        "valid": valid,
        "base": " ".join(base_conditions),
        "base_plain": decode_taf_tokens(base_conditions),
        "changes": " | ".join(changes[:3]),
        "changes_plain": " ".join(decode_taf_change_group(group) for group in changes[:3] if group),
    }


def extract_taf_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if TAF_LINE_RE.match(stripped):
            if current:
                blocks.append(current)
            current = [stripped]
        elif current:
            current.append(stripped)
    if current:
        blocks.append(current)
    return blocks


def build_station_specific_metar_view(product: EmwinProduct, decoded: dict[str, str]) -> dict[str, object]:
    summary = decoded["summary"]
    if decoded["temperature_detail"]:
        summary += (
            ". Temperature / dew point are air temperature and moisture saturation point: "
            f"{decoded['temperature_detail']}"
        )
    return {
        "headline": f"Local hourly observation at {_friendly_zulu_time(decoded['time'])}",
        "summary": summary,
        "report_label": f"SAHOURLY ({_friendly_utc(product.receipt_time.isoformat())})",
        "weather_details": {
            "wind": decoded["wind_text"],
            "wind_degrees": int(decoded["wind_degrees"]) if decoded["wind_degrees"] else None,
            "visibility": decoded["visibility_text"],
            "weather": decoded["weather_text"],
            "sky": decoded["sky_text"],
            "temperature_f": decoded["temperature_f"],
            "dew_point_f": decoded["dew_point_f"],
            "pressure": decoded["pressure_text"],
        },
    }


def build_station_specific_taf_view(product: EmwinProduct, decoded: dict[str, str]) -> dict[str, object]:
    summary = f"Forecast valid {decoded['valid']}: {decoded['base_plain']}"
    if decoded["changes_plain"]:
        summary += f". Expected changes: {decoded['changes_plain']}"
    return {
        "headline": f"Local terminal forecast issued {_friendly_zulu_time(decoded['issued'])}",
        "summary": summary,
        "report_label": f"TAFALLUS ({_friendly_utc(product.receipt_time.isoformat())})",
        "weather_details": {},
    }


def build_station_specific_product_view(
    text: str,
    product: EmwinProduct,
    station_code: str,
) -> dict[str, object] | None:
    lines = split_nonempty_lines(text)

    if product.awips_id == "SAHOURLY":
        for line in lines:
            decoded = decode_metar_line(line.strip())
            if decoded and decoded["station"] == station_code:
                return build_station_specific_metar_view(product, decoded)

    if product.awips_id == "TAFALLUS":
        for block in extract_taf_blocks(lines):
            decoded = decode_taf_block(block)
            if decoded and decoded["station"] == station_code:
                return build_station_specific_taf_view(product, decoded)

    return None


def build_specialized_text_details(text: str, product: EmwinProduct) -> tuple[str, str, tuple[tuple[str, str], ...]] | None:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    if product.awips_id == "SAHOURLY":
        metars: list[dict[str, str]] = []
        for line in lines:
            decoded = decode_metar_line(line.strip())
            if decoded:
                metars.append(decoded)
        if metars:
            bulletin_name = next((line.strip() for line in lines if line.strip() == "METAR"), "METAR")
            count = len(metars)
            return (
                f"SAHOURLY · {bulletin_name}",
                f"{count} bundled report{'s' if count != 1 else ''}",
                (),
            )

        fallback_entries = build_sahourly_fallback_entries(lines)
        if fallback_entries:
            return (
                "SAHOURLY · Observations",
                f"{len(fallback_entries)} bundled report{'s' if len(fallback_entries) != 1 else ''}",
                (),
            )
        return None

    if product.awips_id == "TAFALLUS":
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if TAF_LINE_RE.match(stripped):
                if current:
                    blocks.append(current)
                current = [stripped]
            elif current:
                current.append(stripped)
        if current:
            blocks.append(current)

        tafs = [decoded for block in blocks if (decoded := decode_taf_block(block))]
        if not tafs:
            return None

        bulletin_name = next((line.strip() for line in lines if line.strip() == "TAF"), "TAF")
        count = len(tafs)
        return (
            f"TAFALLUS · {bulletin_name}",
            f"{count} bundled forecast{'s' if count != 1 else ''}",
            (),
        )

    if product.family == "MIS":
        reports = [decode_metar_line(line.strip()) for line in lines if decode_metar_line(line.strip())]
        reports = [report for report in reports if report]
        if reports:
            return (
                f"{product.awips_id} · Observation Bundle",
                f"{len(reports)} bundled report{'s' if len(reports) != 1 else ''}",
                (),
            )
        raw_entries = build_mis_fallback_entries(lines)
        if not raw_entries:
            return None
        return (
            f"{product.awips_id} · Marine Summary",
            f"{len(raw_entries)} bundled entr{'ies' if len(raw_entries) != 1 else 'y'}",
            (),
        )

    return None


def build_related_reports(text: str, product: EmwinProduct) -> tuple[tuple[str, str, str], ...]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    if product.awips_id == "SAHOURLY":
        reports: list[tuple[str, str, str]] = []
        for line in lines:
            decoded = decode_metar_line(line.strip())
            if decoded:
                reports.append((decoded["station"], decoded["summary"], ""))
        if reports:
            return tuple(reports)
        return build_sahourly_fallback_entries(lines)

    if product.awips_id == "TAFALLUS":
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if TAF_LINE_RE.match(stripped):
                if current:
                    blocks.append(current)
                current = [stripped]
            elif current:
                current.append(stripped)
        if current:
            blocks.append(current)

        reports: list[tuple[str, str, str]] = []
        for block in blocks:
            decoded = decode_taf_block(block)
            if decoded:
                summary = f"Valid {decoded['valid']}: {decoded['base']}"
                if decoded["changes"]:
                    summary += f". Changes: {decoded['changes']}"
                plain = f"Forecast covers {decoded['valid']} with starting conditions {decoded['base']}."
                if decoded["changes_plain"]:
                    plain += f" {decoded['changes_plain']}."
                reports.append((decoded["station"], summary, plain))
        return tuple(reports)

    if product.family == "MIS":
        reports: list[tuple[str, str, str]] = []
        for line in lines:
            decoded = decode_metar_line(line.strip())
            if decoded:
                reports.append((decoded["station"], decoded["summary"], ""))
        if reports:
            return tuple(reports)
        return build_mis_fallback_entries(lines)

    return ()


def build_mis_fallback_entries(lines: list[str]) -> tuple[tuple[str, str, str], ...]:
    entries: list[tuple[str, str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or WMO_RE.match(stripped) or stripped in {"SPECI", "METAR"}:
            continue
        if len(stripped) < 20:
            continue
        code = stripped.split()[0]
        entries.append((code, stripped[:220], "Bundled coded marine or observation entry."))
    return tuple(entries[:24])


def build_sahourly_fallback_entries(lines: list[str]) -> tuple[tuple[str, str, str], ...]:
    entries: list[tuple[str, str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or WMO_RE.match(stripped) or stripped == "METAR":
            continue
        if len(stripped) < 6 or "=" not in stripped:
            continue
        code = stripped.split()[0]
        entries.append((code, stripped, "Raw bundled observation entry."))
    return tuple(entries[:24])


def analyze_text_product(
    text: str,
    product: EmwinProduct,
    airport_index: dict[str, StationLocation],
) -> dict[str, object]:
    title, summary = summarise_text(text, product.awips_id)
    lines = split_nonempty_lines(text)
    station_codes = extract_station_codes(text, product, airport_index)
    lat_lon_centroid = parse_lat_lon_centroid(text)
    detail_sections: tuple[tuple[str, str], ...] = ()
    related_reports: tuple[tuple[str, str, str], ...] = ()
    station_views: dict[str, dict[str, object]] = {}

    if product.awips_id == "SAHOURLY":
        metars = [decoded for line in lines if (decoded := decode_metar_line(line.strip()))]
        if metars:
            count = len(metars)
            title = f"Hourly METAR roundup: {count} stations"
            summary = "Latest raw bulletin line: " + " | ".join(
                f"{decoded['station']} {decoded['time']}" for decoded in metars[:4]
            )
            detail_sections = (
                ("Stations", ", ".join(decoded["station"] for decoded in metars[:8])),
                ("Latest decoded", metars[0]["summary"][:220]),
            )
            related_reports = tuple((decoded["station"], decoded["summary"], "") for decoded in metars)
            station_views = {
                decoded["station"]: build_station_specific_metar_view(product, decoded)
                for decoded in metars
            }
        else:
            fallback_entries = build_sahourly_fallback_entries(lines)
            if fallback_entries:
                count = len(fallback_entries)
                title = f"Hourly METAR roundup: {count} stations"
                summary = f"{count} bundled report{'s' if count != 1 else ''}"
                related_reports = fallback_entries

    elif product.awips_id == "TAFALLUS":
        tafs = [decoded for block in extract_taf_blocks(lines) if (decoded := decode_taf_block(block))]
        if tafs:
            count = len(tafs)
            title = f"Terminal forecasts: {count} stations"
            summary = f"{tafs[0]['station']} valid {tafs[0]['valid']}: {tafs[0]['base']}"
            detail_sections_list = [("Base conditions", tafs[0]["base_plain"][:220])]
            if tafs[0]["changes"]:
                detail_sections_list.append(("Changes", tafs[0]["changes"][:220]))
            detail_sections = tuple(detail_sections_list)
            related_reports = tuple(
                (
                    decoded["station"],
                    (
                        f"Valid {decoded['valid']}: {decoded['base_plain']}"
                        + (f". Changes: {decoded['changes_plain']}" if decoded["changes_plain"] else "")
                    ),
                    (
                        f"Forecast covers {decoded['valid']} with starting conditions {decoded['base_plain']}."
                        + (f" {decoded['changes_plain']}." if decoded["changes_plain"] else "")
                    ),
                )
                for decoded in tafs
            )
            station_views = {
                decoded["station"]: build_station_specific_taf_view(product, decoded)
                for decoded in tafs
            }

    elif product.family == "MIS":
        reports = [decoded for line in lines if (decoded := decode_metar_line(line.strip()))]
        if reports:
            title = f"{product.awips_id} observation bundle"
            summary = f"{len(reports)} bundled report{'s' if len(reports) != 1 else ''}"
            detail_sections = (
                ("Stations", ", ".join(report["station"] for report in reports[:8])),
                ("Latest decoded", reports[0]["summary"][:220]),
            )
            related_reports = tuple((report["station"], report["summary"], "") for report in reports)
        else:
            raw_entries = build_mis_fallback_entries(lines)
            if raw_entries:
                title = f"{product.awips_id} marine summary"
                summary = f"{len(raw_entries)} bundled entr{'ies' if len(raw_entries) != 1 else 'y'}"
                related_reports = raw_entries

    if not detail_sections:
        detail_sections = build_detail_sections(text, product, airport_index, station_codes, lat_lon_centroid)
    if not related_reports:
        related_reports = build_related_reports(text, product)

    return {
        "title": title,
        "summary": summary,
        "station_codes": station_codes,
        "lat_lon_centroid": lat_lon_centroid,
        "detail_sections": detail_sections,
        "related_reports": related_reports,
        "station_views": station_views,
    }


def build_detail_sections(
    text: str,
    product: EmwinProduct,
    airport_index: dict[str, StationLocation],
    station_codes: tuple[str, ...],
    lat_lon_centroid: tuple[float, float] | None,
) -> tuple[tuple[str, str], ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ()

    specialized = build_specialized_text_details(text, product)
    if specialized:
        return specialized[2]

    details: list[tuple[str, str]] = []
    if station_codes:
        named_codes = []
        for code in station_codes[:6]:
            location = airport_index.get(code)
            named_codes.append(f"{code} ({location.city})" if location and location.city else code)
        details.append(("Stations", ", ".join(named_codes)))

    report_lines = [line for line in lines if REPORT_LINE_RE.match(line)]
    if report_lines:
        details.append(("Reports", f"{len(report_lines)} reports. Latest: {report_lines[0][:96]}"))

    if lat_lon_centroid:
        lat, lon = lat_lon_centroid
        details.append(("Centroid", f"{lat:.2f}, {lon:.2f}"))

    content_lines = [
        line for line in lines[1:]
        if line != product.awips_id and not WMO_RE.match(line) and not REPORT_LINE_RE.match(line)
    ]
    if content_lines:
        details.append(("Highlights", " ".join(content_lines[:3])[:220]))

    return tuple(details[:5])


def extract_station_codes(text: str, product: EmwinProduct, airport_index: dict[str, StationLocation]) -> tuple[str, ...]:
    candidates: set[str] = set()
    if product.originator in airport_index:
        candidates.add(product.originator)

    for raw_line in text.splitlines():
        line = raw_line.strip().upper()
        if not line:
            continue

        taf_match = TAF_LINE_RE.match(line)
        if taf_match:
            code = taf_match.group("code")
            if code in airport_index:
                candidates.add(code)
            continue

        report_match = REPORT_LINE_RE.match(line)
        if report_match:
            code = line.split()[0]
            if code in airport_index:
                candidates.add(code)

    return tuple(sorted(candidates))


def parse_product(path: Path, airport_index: dict[str, StationLocation], root: Path) -> EmwinProduct | None:
    product = parse_filename(path)
    if product is None:
        return None

    relative_path = str(path.resolve().relative_to(root.resolve()))
    product = EmwinProduct(**{**asdict(product), "relative_path": relative_path})

    if product.category == "graphic":
        title, summary, image_category, image_slot = describe_graphic_product(product)
        return EmwinProduct(
            **{
                **asdict(product),
                "station_codes": (),
                "product_type": classify_product_type(product),
                "title": title,
                "summary": summary,
                "detail_sections": (
                    ("Category", GRAPHIC_CATEGORY_LABELS.get(image_category, "Image")),
                    ("Received", product.receipt_time.strftime("%b %d, %Y %H:%M UTC")),
                    ("Format", product.extension.upper()),
                ),
                "image_category": image_category,
                "image_slot": image_slot,
            }
        )

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return product

    title, summary = summarise_text(text, product.awips_id)
    station_codes = extract_station_codes(text, product, airport_index)
    lat_lon_centroid = parse_lat_lon_centroid(text)
    related_reports = build_related_reports(text, product)
    specialized = build_specialized_text_details(text, product)
    if specialized:
        title, summary, detail_sections = specialized
    else:
        detail_sections = build_detail_sections(text, product, airport_index, station_codes, lat_lon_centroid)
    return EmwinProduct(
        **{
            **asdict(product),
            "title": title,
            "summary": summary,
            "station_codes": station_codes,
            "lat_lon_centroid": lat_lon_centroid,
            "product_type": classify_product_type(product),
            "detail_sections": detail_sections,
            "related_reports": related_reports,
        }
    )


def iter_recent_products(root: Path, hours: int, airport_index: dict[str, StationLocation]) -> Iterable[EmwinProduct]:
    cutoff = utc_now() - timedelta(hours=hours)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        product = parse_product(path, airport_index, root)
        if product is None or product.receipt_time < cutoff:
            continue
        yield product


def build_station_summaries(products: list[EmwinProduct], airport_index: dict[str, StationLocation]) -> list[StationSummary]:
    latest_by_code: dict[str, StationSummary] = {}
    warning_centroids: dict[str, list[tuple[float, float]]] = defaultdict(list)
    categories_by_code: dict[str, set[str]] = defaultdict(set)

    for product in products:
        if product.lat_lon_centroid:
            for code in product.station_codes or (product.originator,):
                warning_centroids[code].append(product.lat_lon_centroid)
        for code in product.station_codes:
            categories_by_code[code].add(product.category)

    for product in products:
        for code in product.station_codes:
            location = airport_index.get(code)
            if location is None and warning_centroids.get(code):
                latitude = round(mean(item[0] for item in warning_centroids[code]), 4)
                longitude = round(mean(item[1] for item in warning_centroids[code]), 4)
                location = StationLocation(
                    code=code,
                    name=f"{code} derived centroid",
                    city="Derived from bulletin polygon",
                    subdivision="",
                    country="US",
                    latitude=latitude,
                    longitude=longitude,
                    source="warning-centroid",
                )
            if location is None:
                continue

            item = latest_by_code.get(code)
            if item is None:
                item = StationSummary(
                    code=code,
                    name=location.name,
                    city=location.city,
                    subdivision=location.subdivision,
                    country=location.country,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    source=location.source,
                    latest_seen=product.receipt_time,
                    marker_kind="text",
                )
                latest_by_code[code] = item

            if product.receipt_time > item.latest_seen:
                item.latest_seen = product.receipt_time

            station_view: dict[str, object] | None = None
            if product.category == "text":
                try:
                    text = Path(product.path).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    text = ""
                if text:
                    station_view = build_station_specific_product_view(text, product, code)

            if station_view and not item.weather_summary:
                item.weather_summary = str(station_view["summary"])
                item.weather_time = product.receipt_time
                item.weather_details = dict(station_view.get("weather_details", {}))

            if len(item.products) < 6:
                item.products.append(
                    {
                        "awips_id": product.awips_id,
                        "title": station_view["headline"] if station_view else product.title,
                        "summary": station_view["summary"] if station_view else product.summary,
                        "time": product.receipt_time.isoformat(),
                        "filename": product.filename,
                        "feed_id": make_feed_id(product.filename),
                        "category": product.category,
                        "product_type": product.product_type,
                        "relative_path": product.relative_path,
                        "report_label": station_view["report_label"] if station_view else f"{product.awips_id} ({_friendly_utc(product.receipt_time.isoformat())})",
                    }
                )

    stations = list(latest_by_code.values())
    for station in stations:
        categories = categories_by_code.get(station.code, {"text"})
        if categories == {"graphic"}:
            station.marker_kind = "graphic"
        elif {"graphic", "text"}.issubset(categories):
            station.marker_kind = "mixed"
        else:
            station.marker_kind = "text"
    stations.sort(key=lambda item: (item.code, -item.latest_seen.timestamp()))
    return stations


def serialize_product(product: EmwinProduct) -> dict[str, object]:
    return {
        "path": product.path,
        "relative_path": product.relative_path,
        "filename": product.filename,
        "feed_id": make_feed_id(product.filename),
        "category": product.category,
        "awips_id": product.awips_id,
        "family": product.family,
        "originator": product.originator,
        "source": product.source,
        "receipt_time": product.receipt_time.isoformat(),
        "title": product.title,
        "summary": product.summary,
        "extension": product.extension,
        "station_codes": list(product.station_codes),
        "lat_lon_centroid": list(product.lat_lon_centroid) if product.lat_lon_centroid else None,
        "detail_sections": [{"label": label, "value": value} for label, value in product.detail_sections],
        "product_type": product.product_type,
        "image_category": product.image_category,
        "image_slot": product.image_slot,
        "related_reports": [
            {"code": code, "summary": summary, "plain": plain}
            for code, summary, plain in product.related_reports
        ],
    }


def serialize_station(station: StationSummary) -> dict[str, object]:
    return {
        "code": station.code,
        "name": station.name,
        "city": station.city,
        "subdivision": station.subdivision,
        "country": station.country,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "source": station.source,
        "latest_seen": station.latest_seen.isoformat(),
        "products": station.products,
        "marker_kind": station.marker_kind,
        "weather_summary": station.weather_summary,
        "weather_time": station.weather_time.isoformat() if station.weather_time else None,
        "weather_details": station.weather_details,
    }


def select_radar_composite_sources(images: list[EmwinProduct]) -> list[EmwinProduct]:
    latest_by_slot: dict[str, EmwinProduct] = {}
    for image in sorted(images, key=lambda item: item.receipt_time, reverse=True):
        if image.category != "graphic" or not image.awips_id.startswith("RAD"):
            continue
        slot = image.image_slot
        if slot not in RADAR_COMPOSITE_GRID:
            continue
        if slot not in latest_by_slot:
            latest_by_slot[slot] = image

    return sorted(
        latest_by_slot.values(),
        key=lambda item: (RADAR_COMPOSITE_GRID[item.image_slot][1], RADAR_COMPOSITE_GRID[item.image_slot][0]),
    )


def radar_composite_signature(products: list[EmwinProduct]) -> str:
    return "|".join(
        f"{product.image_slot}:{product.relative_path}:{product.receipt_time.isoformat()}"
        for product in products
    )


def render_radar_composite_image(products: list[EmwinProduct]) -> bytes:
    if not products:
        raise ValueError("No radar products supplied for composite rendering.")

    frames: list[tuple[EmwinProduct, Image.Image]] = []
    for product in products:
        with Image.open(product.path) as handle:
            frames.append((product, handle.convert("RGB")))

    try:
        key_height = min(
            RADAR_COMPOSITE_KEY_HEIGHT,
            min(max(1, frame.height // 5) for _, frame in frames),
        )
        cell_width = max(frame.width for _, frame in frames)
        cell_height = max(frame.height - key_height for _, frame in frames)
        cols = max(col for col, _ in RADAR_COMPOSITE_GRID.values()) + 1
        rows = max(row for _, row in RADAR_COMPOSITE_GRID.values()) + 1
        rendered = Image.new("RGB", (cell_width * cols, (cell_height * rows) + key_height), (255, 255, 255))

        latest_product = max(products, key=lambda item: item.receipt_time)
        latest_frame = next(frame for product, frame in frames if product is latest_product)
        legend = latest_frame.crop((0, latest_frame.height - key_height, latest_frame.width, latest_frame.height))

        for product, frame in frames:
            slot = product.image_slot
            if slot not in RADAR_COMPOSITE_GRID:
                continue
            col, row = RADAR_COMPOSITE_GRID[slot]
            body = frame.crop((0, 0, frame.width, frame.height - key_height))
            x = col * cell_width
            y = row * cell_height
            rendered.paste(body, (x, y))

        legend_x = (rendered.width - legend.width) // 2
        legend_y = rendered.height - key_height
        rendered.paste(legend, (legend_x, legend_y))

        buffer = io.BytesIO()
        rendered.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        for _, frame in frames:
            frame.close()


def build_radar_composite_state(images: list[EmwinProduct]) -> dict[str, object] | None:
    sources = select_radar_composite_sources(images)
    if not sources:
        return None

    latest = max(sources, key=lambda item: item.receipt_time)
    oldest = min(sources, key=lambda item: item.receipt_time)
    return {
        "title": "National radar composite",
        "summary": (
            f"Composite render of the latest {len(sources)} regional radar mosaics at native pixel size, "
            "with the current color key copied to the bottom."
        ),
        "frame_count": len(sources),
        "latest_receipt_time": latest.receipt_time.isoformat(),
        "oldest_receipt_time": oldest.receipt_time.isoformat(),
        "latest_awips_id": latest.awips_id,
        "signature": radar_composite_signature(sources),
    }


def build_dashboard_state(root: Path, hours: int) -> dict[str, object]:
    airport_index = load_airport_index()
    all_products = sorted(iter_recent_products(root, hours, airport_index), key=lambda item: item.receipt_time, reverse=True)
    products = [item for item in all_products if item.category == "text"]
    stations = build_station_summaries(products, airport_index)

    by_family = Counter(item.family for item in products)
    state = {
        "generated_at": utc_now().isoformat(),
        "hours": hours,
        "root": str(root.resolve()),
        "counts": {
            "products": len(products),
            "text_products": sum(1 for item in products if item.category == "text"),
            "graphic_products": sum(1 for item in all_products if item.category == "graphic"),
            "stations": len(stations),
        },
        "families": [
            {"code": code, "label": FAMILY_LABELS.get(code, code), "count": count}
            for code, count in by_family.most_common()
        ],
        "products": [serialize_product(item) for item in products],
        "stations": [serialize_station(item) for item in stations],
    }
    return state


def build_images_state(root: Path, hours: int) -> dict[str, object]:
    airport_index = load_airport_index()
    all_products = sorted(iter_recent_products(root, hours, airport_index), key=lambda item: item.receipt_time, reverse=True)
    images = [item for item in all_products if item.category == "graphic"]
    radar_composite = build_radar_composite_state(images)
    category_counts = Counter(item.image_category or "other" for item in images)
    categories = [
        {
            "key": key,
            "label": GRAPHIC_CATEGORY_LABELS.get(key, key),
            "count": category_counts.get(key, 0),
        }
        for key in ["radar-regions", "satellite", "forecast-alerts", "other"]
        if category_counts.get(key, 0)
    ]
    history_groups: dict[str, list[EmwinProduct]] = defaultdict(list)
    for image in images:
        history_key = f"{image.image_category}:{image.awips_id}"
        history_groups[history_key].append(image)

    grouped_images = []
    for history_key, items in history_groups.items():
        items.sort(key=lambda item: item.receipt_time, reverse=True)
        latest = items[0]
        grouped_images.append(
            {
                "history_key": history_key,
                "category": latest.image_category,
                "awips_id": latest.awips_id,
                "title": latest.title,
                "image_slot": latest.image_slot,
                "frames": [serialize_product(item) for item in items],
                "latest_receipt_time": latest.receipt_time.isoformat(),
            }
        )
    grouped_images.sort(key=lambda item: item["latest_receipt_time"], reverse=True)
    return {
        "generated_at": utc_now().isoformat(),
        "hours": hours,
        "root": str(root.resolve()),
        "counts": {
            "images": len(images),
            "categories": len(categories),
        },
        "categories": categories,
        "radar_composite": radar_composite,
        "images": [serialize_product(item) for item in images],
        "image_groups": grouped_images,
    }


def create_app(root: Path | str = DEFAULT_EMWIN_ROOT, hours: int = DEFAULT_WINDOW_HOURS) -> Flask:
    app = Flask(__name__, template_folder="templates")
    emwin_root = Path(root).resolve()
    app.config["EMWIN_ROOT"] = emwin_root
    app.config["WINDOW_HOURS"] = hours
    app.config["CACHE_TTL_SECONDS"] = 30
    cache: dict[str, object] = {"built_at": None, "state": None}
    composite_cache: dict[str, object] = {
        "signature": None,
        "payload": None,
        "ready": False,
        "started_for": None,
        "error": None,
    }
    composite_lock = threading.Lock()
    composite_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-composite")

    def load_state() -> dict[str, object]:
        now = utc_now()
        built_at = cache["built_at"]
        if (
            isinstance(built_at, datetime)
            and cache["state"] is not None
            and (now - built_at).total_seconds() < app.config["CACHE_TTL_SECONDS"]
        ):
            return cache["state"]  # type: ignore[return-value]

        state = build_dashboard_state(app.config["EMWIN_ROOT"], app.config["WINDOW_HOURS"])
        cache["built_at"] = now
        cache["state"] = state
        return state

    def collect_recent_images() -> list[EmwinProduct]:
        airport_index = load_airport_index()
        all_products = sorted(
            iter_recent_products(app.config["EMWIN_ROOT"], app.config["WINDOW_HOURS"], airport_index),
            key=lambda item: item.receipt_time,
            reverse=True,
        )
        return [item for item in all_products if item.category == "graphic"]

    def ensure_radar_composite_job() -> tuple[dict[str, object] | None, bool]:
        images = collect_recent_images()
        state = build_radar_composite_state(images)
        if state is None:
            with composite_lock:
                composite_cache["signature"] = None
                composite_cache["payload"] = None
                composite_cache["ready"] = False
                composite_cache["started_for"] = None
                composite_cache["error"] = None
            return None, False

        signature = state["signature"]
        with composite_lock:
            if composite_cache["signature"] == signature and composite_cache["ready"]:
                return state, True
            if composite_cache["started_for"] == signature:
                return state, False
            composite_cache["signature"] = signature
            composite_cache["payload"] = None
            composite_cache["ready"] = False
            composite_cache["started_for"] = signature
            composite_cache["error"] = None

        sources = select_radar_composite_sources(images)

        def _render_job() -> None:
            try:
                payload = render_radar_composite_image(sources)
                with composite_lock:
                    if composite_cache["signature"] == signature:
                        composite_cache["payload"] = payload
                        composite_cache["ready"] = True
                        composite_cache["started_for"] = None
            except Exception as exc:
                with composite_lock:
                    if composite_cache["signature"] == signature:
                        composite_cache["payload"] = None
                        composite_cache["ready"] = False
                        composite_cache["started_for"] = None
                        composite_cache["error"] = str(exc)

        composite_executor.submit(_render_job)
        return state, False

    @app.get("/")
    def index():
        state = load_state()
        return render_template("dashboard.html", state=state)

    @app.get("/images")
    def images():
        state = build_images_state(app.config["EMWIN_ROOT"], app.config["WINDOW_HOURS"])
        return render_template("images.html", state=state)

    @app.get("/api/radar-composite")
    def api_radar_composite():
        state, ready = ensure_radar_composite_job()
        if state is None:
            abort(404)
        if not ready:
            return jsonify({"ready": False, "signature": state["signature"]}), 202
        with composite_lock:
            payload = composite_cache["payload"]
        if not isinstance(payload, bytes):
            return jsonify({"ready": False, "signature": state["signature"]}), 202
        return send_file(
            io.BytesIO(payload),
            mimetype="image/png",
            download_name="radar-composite.png",
            max_age=app.config["CACHE_TTL_SECONDS"],
        )

    @app.get("/api/summary")
    def api_summary():
        return jsonify(load_state())

    @app.get("/api/product")
    def api_product():
        relative_path = request.args.get("path", "")
        if not relative_path:
            abort(404)

        requested_path = (app.config["EMWIN_ROOT"] / relative_path).resolve()
        root_path = app.config["EMWIN_ROOT"]
        try:
            requested_path.relative_to(root_path)
        except ValueError:
            abort(403)

        if not requested_path.is_file():
            abort(404)

        return send_file(requested_path)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": app.config["EMWIN_ROOT"].exists(), "root": str(app.config["EMWIN_ROOT"])})

    return app


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the recent-EMWIN dashboard.")
    parser.add_argument("--root", default=str(DEFAULT_EMWIN_ROOT), help="Path to the EMWIN directory.")
    parser.add_argument("--hours", type=int, default=DEFAULT_WINDOW_HOURS, help="Lookback window in hours.")
    parser.add_argument("--host", default="127.0.0.1", help="Flask bind host.")
    parser.add_argument("--port", type=int, default=8080, help="Flask bind port.")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    app = create_app(args.root, args.hours)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0
