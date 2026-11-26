"""Async Open-Meteo geocoding and air quality telemetry service with bounded TTL caches."""

from datetime import UTC, datetime

import httpx
from cachetools import TTLCache

from app.aqi import (
    classify_us_aqi,
    find_forecast_windows,
    identify_dominant_pollutant,
    next_hourly_forecast_points,
    optional_measurement,
    valid_measurement,
)
from app.config import settings
from app.models import AirQualityReport, LocationInfo, PollutantMetrics


class UpstreamServiceError(RuntimeError):
    """Raised when an external telemetry provider fails or returns an invalid payload."""


GEO_CACHE: TTLCache[str, LocationInfo] = TTLCache(maxsize=256, ttl=settings.geo_cache_ttl)
AQI_CACHE: TTLCache[str, AirQualityReport] = TTLCache(maxsize=256, ttl=settings.aqi_cache_ttl)

_AQI_CURRENT_FIELDS = "us_aqi,pm10,pm2_5,nitrogen_dioxide,ozone,carbon_monoxide,sulphur_dioxide"


def _parse_location_payload(payload: object, fallback_city: str) -> LocationInfo | None:
    """Validate Open-Meteo geocoding JSON and extract the top LocationInfo."""
    if not isinstance(payload, dict):
        raise UpstreamServiceError("Invalid geocoding payload")
    results = payload.get("results")
    if not results or not isinstance(results, list):
        return None
    top = results[0]
    if not isinstance(top, dict) or "latitude" not in top or "longitude" not in top:
        raise UpstreamServiceError("Malformed geocoding entry")
    try:
        return LocationInfo(
            name=str(top.get("name") or fallback_city),
            country=str(top.get("country") or "Unknown"),
            latitude=float(top["latitude"]),
            longitude=float(top["longitude"]),
        )
    except (TypeError, ValueError) as exc:
        raise UpstreamServiceError("Invalid location coordinates") from exc


async def fetch_city_location(city: str, client: httpx.AsyncClient) -> LocationInfo | None:
    """Resolve a city name into geographic coordinates with 24-hour caching."""
    cache_key = city.lower()
    if cache_key in GEO_CACHE:
        return GEO_CACHE[cache_key]

    try:
        response = await client.get(
            settings.geocode_url,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=settings.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamServiceError("Geocoding service unavailable") from exc

    location = _parse_location_payload(payload, city)
    if location is not None:
        GEO_CACHE[cache_key] = location
    return location


def _extract_pollutants(current: dict[str, object]) -> PollutantMetrics:
    """Extract optional pollutant measurements without zero-coercing missing readings."""
    return PollutantMetrics(
        pm2_5=optional_measurement(current.get("pm2_5")),
        pm10=optional_measurement(current.get("pm10")),
        no2=optional_measurement(current.get("nitrogen_dioxide")),
        o3=optional_measurement(current.get("ozone")),
        co=optional_measurement(current.get("carbon_monoxide")),
        so2=optional_measurement(current.get("sulphur_dioxide")),
    )


def _build_air_quality_report(payload: dict[str, object]) -> AirQualityReport:
    """Validate Open-Meteo response fields and construct a structured AirQualityReport."""
    current = payload.get("current")
    hourly = payload.get("hourly")
    if not isinstance(current, dict):
        raise UpstreamServiceError("Missing current air quality block")

    try:
        aqi_value = int(valid_measurement(current.get("us_aqi")))
    except ValueError as exc:
        raise UpstreamServiceError("Missing or invalid US AQI reading") from exc

    metrics = _extract_pollutants(current)
    hourly_dict = hourly if isinstance(hourly, dict) else {}
    points = next_hourly_forecast_points(
        current.get("time"),
        hourly_dict.get("time"),
        hourly_dict.get("us_aqi"),
    )
    best_win, worst_win = find_forecast_windows(points, aqi_value)
    meta = classify_us_aqi(aqi_value)
    raw_time = current.get("time")
    measurement_time = str(raw_time) if isinstance(raw_time, str) and raw_time else None

    return AirQualityReport(
        us_aqi=aqi_value,
        category=meta["category"],
        risk_level=meta["risk"],
        badge=meta["badge"],
        dominant_pollutant=identify_dominant_pollutant(metrics),
        pollutants=metrics,
        hourly_forecast=[p.us_aqi for p in points],
        forecast_points=points,
        best_window=best_win,
        worst_window=worst_win,
        measurement_time=measurement_time,
        timezone=str(payload.get("timezone") or "GMT"),
        data_source=(
            f"Open-Meteo CAMS Global Model (modeled estimate as of "
            f"{datetime.now(UTC).strftime('%H:%M UTC')}, not ground station)"
        ),
        is_cached=False,
    )


async def fetch_air_quality_report(
    lat: float, lon: float, client: httpx.AsyncClient
) -> AirQualityReport:
    """Retrieve live pollutants and 12-hour US AQI forecast with 15-minute TTL caching."""
    cache_key = f"{round(lat, 2)}:{round(lon, 2)}"
    if cache_key in AQI_CACHE:
        return AQI_CACHE[cache_key].model_copy(update={"is_cached": True})

    try:
        response = await client.get(
            settings.air_quality_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": _AQI_CURRENT_FIELDS,
                "hourly": "us_aqi",
                "forecast_days": 2,
                "timezone": "auto",
            },
            timeout=settings.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamServiceError("Air quality telemetry service unavailable") from exc

    if not isinstance(payload, dict):
        raise UpstreamServiceError("Invalid air quality response payload")

    report = _build_air_quality_report(payload)
    AQI_CACHE[cache_key] = report
    return report
