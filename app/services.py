"""
Environmental telemetry fetching, caching, pollutant analysis, and Gemini AI advisory services.
"""

import logging
import re
from typing import Dict, List, Optional
import httpx
from cachetools import TTLCache

from app.config import settings
from app.models import (
    AIAdvisory,
    AirQualityReport,
    LocationInfo,
    PollutantMetrics,
    SensitivityProfile,
)

logger = logging.getLogger(__name__)

GEO_CACHE: TTLCache[str, LocationInfo] = TTLCache(maxsize=256, ttl=settings.geo_cache_ttl)
AQI_CACHE: TTLCache[str, AirQualityReport] = TTLCache(maxsize=256, ttl=settings.aqi_cache_ttl)


def sanitize_city_input(raw_city: str) -> str:
    """Strip unsafe characters to prevent XSS and prompt injection."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-,.]", "", raw_city.strip())
    return re.sub(r"\s+", " ", cleaned)[:80]


def classify_us_aqi(aqi: int) -> Dict[str, str]:
    """Map numeric US AQI value to EPA category, exposure risk, and accessible badge."""
    if aqi <= 50:
        return {"category": "Good", "risk": "Low", "badge": "GOOD"}
    if aqi <= 100:
        return {"category": "Moderate", "risk": "Moderate", "badge": "MODERATE"}
    if aqi <= 150:
        return {"category": "Unhealthy for Sensitive Groups", "risk": "Elevated", "badge": "SENSITIVE"}
    if aqi <= 200:
        return {"category": "Unhealthy", "risk": "High", "badge": "UNHEALTHY"}
    if aqi <= 300:
        return {"category": "Very Unhealthy", "risk": "Very High", "badge": "VERY_UNHEALTHY"}
    return {"category": "Hazardous", "risk": "Severe", "badge": "HAZARDOUS"}


def identify_dominant_pollutant(metrics: PollutantMetrics) -> str:
    """Determine the primary contributing pollutant relative to WHO reference thresholds."""
    ratios = {
        "PM2.5 (Fine Particulates)": metrics.pm2_5 / 15.0,
        "PM10 (Coarse Dust)": metrics.pm10 / 45.0,
        "NO₂ (Traffic Emissions)": metrics.no2 / 25.0,
        "O₃ (Ground Ozone)": metrics.o3 / 100.0,
    }
    return max(ratios, key=ratios.get)


async def fetch_city_location(city: str, client: httpx.AsyncClient) -> Optional[LocationInfo]:
    """Resolve a city name into geographic coordinates with 24-hour caching."""
    cache_key = city.lower()
    if cache_key in GEO_CACHE:
        return GEO_CACHE[cache_key]

    response = await client.get(
        settings.geocode_url,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=settings.http_timeout,
    )
    response.raise_for_status()
    results = response.json().get("results")
    if not results:
        return None

    top = results[0]
    location = LocationInfo(
        name=top.get("name", city),
        country=top.get("country", "Unknown"),
        latitude=float(top["latitude"]),
        longitude=float(top["longitude"]),
    )
    GEO_CACHE[cache_key] = location
    return location


async def fetch_air_quality_report(
    lat: float, lon: float, client: httpx.AsyncClient
) -> AirQualityReport:
    """Retrieve live pollutants and 12-hour US AQI forecast with 15-minute TTL caching."""
    cache_key = f"{round(lat, 2)}:{round(lon, 2)}"
    if cache_key in AQI_CACHE:
        return AQI_CACHE[cache_key]

    response = await client.get(
        settings.air_quality_url,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm10,pm2_5,nitrogen_dioxide,ozone",
            "hourly": "us_aqi",
            "forecast_days": 1,
        },
        timeout=settings.http_timeout,
    )
    response.raise_for_status()
    payload = response.json()

    current = payload.get("current", {})
    hourly = payload.get("hourly", {})
    aqi_value = int(current.get("us_aqi") or 0)
    meta = classify_us_aqi(aqi_value)

    metrics = PollutantMetrics(
        pm2_5=round(float(current.get("pm2_5") or 0.0), 1),
        pm10=round(float(current.get("pm10") or 0.0), 1),
        no2=round(float(current.get("nitrogen_dioxide") or 0.0), 1),
        o3=round(float(current.get("ozone") or 0.0), 1),
    )

    raw_forecast: List[Optional[int]] = (hourly.get("us_aqi") or [])[:12]
    clean_forecast = [int(val) if val is not None else aqi_value for val in raw_forecast]
    if not clean_forecast:
        clean_forecast = [aqi_value] * 6

    report = AirQualityReport(
        us_aqi=aqi_value,
        category=meta["category"],
        risk_level=meta["risk"],
        badge=meta["badge"],
        dominant_pollutant=identify_dominant_pollutant(metrics),
        pollutants=metrics,
        hourly_forecast=clean_forecast,
    )
    AQI_CACHE[cache_key] = report
    return report


def build_fallback_advisory(
    city: str, profile: SensitivityProfile, report: AirQualityReport
) -> AIAdvisory:
    """Provide deterministic environmental guidance when external LLM service is unavailable."""
    aqi = report.us_aqi
    dominant = report.dominant_pollutant

    if aqi <= 50:
        health = f"Clean air in {city} (AQI {aqi}). Safe for unrestricted outdoor exercise and ventilation."
        commute = "Walking, cycling, and open-window transit are optimal across all city corridors."
    elif aqi <= 100:
        health = f"Moderate air in {city} (AQI {aqi}, driven by {dominant}). {profile} users should pace prolonged exertion."
        commute = "Standard commuting is safe; prefer tree-lined routes away from congested intersections."
    elif aqi <= 150:
        health = f"Elevated pollution in {city} (AQI {aqi}, {dominant}). {profile} groups should limit outdoor duration."
        commute = "Wear an N95 mask near heavy traffic and keep vehicle cabin air on recirculation."
    else:
        health = f"Unhealthy air alert in {city} (AQI {aqi}, {dominant}). Minimize outdoor exposure and run HEPA filtration."
        commute = "Mandatory N95/KN95 respirator outdoors; avoid peak rush-hour transit."

    urban = (
        f"Target {dominant} through localized anti-smog misting, construction dust audits, "
        f"and synchronized traffic signal green-waves."
    )
    return AIAdvisory(
        health=health,
        commute=commute,
        urban=urban,
        source="Environmental Rules Fallback Engine",
    )


async def generate_genai_advisory(
    city: str,
    profile: SensitivityProfile,
    report: AirQualityReport,
    client: httpx.AsyncClient,
) -> AIAdvisory:
    """Generate context-aware health, commute, and civic guidance using Google Gemini 2.5 Flash."""
    if not settings.gemini_api_key or settings.gemini_api_key == "your_google_gemini_api_key_here":
        return build_fallback_advisory(city, profile, report)

    p = report.pollutants
    prompt = (
        f"You are an Urban Air Quality & Public Health AI Assistant.\n"
        f"City: {city} | Profile: {profile}\n"
        f"Metrics: US AQI={report.us_aqi} ({report.category}), Dominant={report.dominant_pollutant}, "
        f"PM2.5={p.pm2_5} ug/m3, PM10={p.pm10} ug/m3, NO2={p.no2} ug/m3, O3={p.o3} ug/m3.\n"
        f"Respond in exactly 3 concise, actionable lines (max 30 words each) with these exact prefixes:\n"
        f"HEALTH: <personalized health & outdoor activity guidance>\n"
        f"COMMUTE: <safe travel, mask & indoor ventilation tip>\n"
        f"URBAN: <municipal/civic mitigation action targeting the dominant pollutant>"
    )

    try:
        response = await client.post(
            f"{settings.gemini_url}?key={settings.gemini_api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": 240},
            },
            timeout=10.0,
        )
        response.raise_for_status()
        raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]

        parsed: Dict[str, str] = {}
        for line in raw_text.splitlines():
            clean = line.replace("*", "").strip()
            for prefix in ("HEALTH:", "COMMUTE:", "URBAN:"):
                if clean.upper().startswith(prefix):
                    parsed[prefix[:-1].lower()] = clean.split(":", 1)[1].strip()

        if parsed.get("health") and parsed.get("commute"):
            return AIAdvisory(
                health=parsed["health"],
                commute=parsed["commute"],
                urban=parsed.get("urban")
                or f"Prioritize mitigation of {report.dominant_pollutant} in high-density zones.",
                source="Google Gemini 2.5 Flash",
            )
    except Exception as exc:
        logger.warning("Falling back to rule-based advisory due to Gemini error: %s", exc)

    return build_fallback_advisory(city, profile, report)
