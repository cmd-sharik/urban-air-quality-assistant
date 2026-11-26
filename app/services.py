"""Backwards-compatible service facade exporting AQI, telemetry, decision, and AI helpers."""

from app.ai_advisor import generate_genai_advisory, parse_gemini_advisory
from app.aqi import (
    classify_us_aqi,
    identify_dominant_pollutant,
    next_hourly_forecast_points,
    sanitize_city_input,
    valid_measurement,
)
from app.decision_engine import build_deterministic_advisory as build_fallback_advisory
from app.telemetry import AQI_CACHE, GEO_CACHE, fetch_air_quality_report, fetch_city_location


def next_hourly_forecast(current_time: object, timestamps: object, values: object) -> list[int]:
    """Return consecutive future hourly US AQI integers for legacy callers."""
    return [p.us_aqi for p in next_hourly_forecast_points(current_time, timestamps, values)]


__all__ = [
    "AQI_CACHE",
    "GEO_CACHE",
    "build_fallback_advisory",
    "classify_us_aqi",
    "fetch_air_quality_report",
    "fetch_city_location",
    "generate_genai_advisory",
    "identify_dominant_pollutant",
    "next_hourly_forecast",
    "next_hourly_forecast_points",
    "parse_gemini_advisory",
    "sanitize_city_input",
    "valid_measurement",
]
