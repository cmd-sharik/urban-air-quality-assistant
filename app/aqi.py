"""Pure deterministic AQI classification, pollutant analysis, and forecast windowing."""

import math
import re
import unicodedata
from datetime import datetime, timedelta
from typing import TypedDict

from app.config import AQI_BANDS, WHO_THRESHOLDS
from app.models import ForecastPoint, ForecastWindow, PollutantMetrics

_ALLOWED_PUNCTUATION = frozenset("-,.")


class AQIClassification(TypedDict):
    """Human-readable category metadata for a US AQI value."""

    category: str
    risk: str
    badge: str


def _is_safe_city_char(char: str) -> bool:
    """Allow letters, combining marks (e.g. Devanagari matras), digits, spaces, - , and ."""
    return (
        char in _ALLOWED_PUNCTUATION
        or char.isspace()
        or unicodedata.category(char)[0] in {"L", "M", "N"}
    )


def sanitize_city_input(raw_city: str) -> str:
    """Strip unsafe characters (XSS / prompt injection) while preserving Unicode names."""
    cleaned = "".join(char for char in raw_city.strip() if _is_safe_city_char(char))
    return re.sub(r"\s+", " ", cleaned).strip()[:80]


def classify_us_aqi(aqi: int) -> AQIClassification:
    """Map numeric US AQI value to EPA category, exposure risk, and accessible badge."""
    for band in AQI_BANDS:
        if aqi <= band.max_aqi:
            return {"category": band.category, "risk": band.risk_level, "badge": band.badge}
    last = AQI_BANDS[-1]
    return {"category": last.category, "risk": last.risk_level, "badge": last.badge}


def valid_measurement(value: object) -> float:
    """Reject absent, nonnumeric, negative, or nonfinite provider measurements."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid air quality measurement")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid air quality measurement")
    return float(value)


def optional_measurement(value: object, digits: int = 1) -> float | None:
    """Parse an optional pollutant reading, returning None when absent or invalid."""
    if value is None:
        return None
    try:
        return round(valid_measurement(value), digits)
    except ValueError:
        return None


def identify_dominant_pollutant(metrics: PollutantMetrics) -> str:
    """Determine the primary contributing pollutant relative to WHO 2021 guidelines."""
    ratios: dict[str, float] = {}
    for field_name, (label, guideline) in WHO_THRESHOLDS.items():
        val = getattr(metrics, field_name)
        if val is not None:
            ratios[label] = val / guideline

    if not ratios:
        return "PM2.5 / Particulate Matter (Primary Metric)"
    return max(ratios, key=lambda pollutant: ratios[pollutant])


def _hour_key(stamp: object) -> str | None:
    """Extract YYYY-MM-DDTHH prefix from an ISO timestamp string."""
    if not isinstance(stamp, str):
        return None
    trimmed = stamp.strip()
    if len(trimmed) < 13:
        return None
    try:
        parsed = datetime.fromisoformat(trimmed[:16])
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%dT%H")


def _format_hhmm(stamp: str) -> str:
    """Format an ISO timestamp string to HH:MM without shifting timezones."""
    if len(stamp) >= 16 and stamp[10] in {"T", " "}:
        return stamp[11:16]
    return stamp


def _plus_one_hour_label(stamp: str) -> str:
    """Add one hour to an ISO timestamp string for window end display."""
    try:
        dt = datetime.fromisoformat(stamp[:16]) + timedelta(hours=1)
        return dt.strftime("%H:%M")
    except ValueError:
        return _format_hhmm(stamp)


def _build_hourly_lookup(
    current_key: str, timestamps: list[object], values: list[object]
) -> dict[str, int]:
    """Index valid future hourly AQI readings by YYYY-MM-DDTHH key."""
    lookup: dict[str, int] = {}
    for raw_ts, raw_val in zip(timestamps, values, strict=False):
        key = _hour_key(raw_ts)
        if key is None or key <= current_key or key in lookup:
            continue
        try:
            lookup[key] = int(valid_measurement(raw_val))
        except ValueError:
            continue
    return lookup


def next_hourly_forecast_points(
    current_time: object, timestamps: object, values: object, limit: int = 12
) -> list[ForecastPoint]:
    """Return consecutive future hourly forecast points without inventing missing values."""
    current_key = _hour_key(current_time)
    if current_key is None or not isinstance(timestamps, list) or not isinstance(values, list):
        return []

    lookup = _build_hourly_lookup(current_key, timestamps, values)
    points: list[ForecastPoint] = []
    start_dt = datetime.fromisoformat(f"{current_key}:00")
    for offset in range(1, limit + 1):
        dt = start_dt + timedelta(hours=offset)
        key = dt.strftime("%Y-%m-%dT%H")
        if key not in lookup:
            break
        points.append(ForecastPoint(time=dt.strftime("%Y-%m-%dT%H:00"), us_aqi=lookup[key]))
    return points


def find_forecast_windows(
    points: list[ForecastPoint], current_aqi: int
) -> tuple[ForecastWindow | None, ForecastWindow | None]:
    """Identify the cleanest and most polluted 2-hour windows in available forecast points."""
    if len(points) < 2:
        return None, None

    candidates: list[ForecastWindow] = []
    for idx in range(len(points) - 1):
        first = points[idx]
        second = points[idx + 1]
        avg_aqi = round((first.us_aqi + second.us_aqi) / 2)
        start_lbl = _format_hhmm(first.time)
        end_lbl = _plus_one_hour_label(second.time)
        candidates.append(
            ForecastWindow(
                start_time=first.time,
                end_time=second.time,
                average_aqi=avg_aqi,
                label=f"{start_lbl}-{end_lbl}",
            )
        )

    best = min(candidates, key=lambda w: w.average_aqi)
    worst = max(candidates, key=lambda w: w.average_aqi)
    if best.average_aqi >= current_aqi and best.average_aqi > 100:
        return None, worst
    return best, worst
