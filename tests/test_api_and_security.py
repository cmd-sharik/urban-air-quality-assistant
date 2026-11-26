"""Integration tests for FastAPI endpoints, security controls, rate limits, and UI HTML."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.aqi import classify_us_aqi
from app.main import app, limiter
from app.models import AIAdvisory, AirQualityReport, LocationInfo, PollutantMetrics
from app.services import next_hourly_forecast
from app.telemetry import AQI_CACHE, GEO_CACHE, UpstreamServiceError

client = TestClient(app)
LOCATION = LocationInfo(name="Jaipur", country="India", latitude=26.91, longitude=75.78)


def make_report(aqi: int = 95) -> AirQualityReport:
    meta = classify_us_aqi(aqi)
    return AirQualityReport(
        us_aqi=aqi,
        category=meta["category"],
        risk_level=meta["risk"],
        badge=meta["badge"],
        dominant_pollutant="PM10 (Coarse Dust)",
        pollutants=PollutantMetrics(pm2_5=32.0, pm10=68.0, no2=18.0, o3=42.0),
        hourly_forecast=[90, 92, 95, 98, 100, 96],
    )


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    limiter.reset()
    GEO_CACHE.clear()
    AQI_CACHE.clear()
    yield
    limiter.reset()
    GEO_CACHE.clear()
    AQI_CACHE.clear()


def test_health_and_static_assets() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "healthy"
    assert "gemini_configured" in body
    assert "gemini_api_key" not in body

    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_security_and_cache_headers() -> None:
    api_headers = client.get("/api/health").headers
    assert api_headers["X-Content-Type-Options"] == "nosniff"
    assert api_headers["X-Frame-Options"] == "DENY"
    assert api_headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert api_headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert api_headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in api_headers["Content-Security-Policy"]
    assert "object-src 'none'" in api_headers["Content-Security-Policy"]
    assert "max-age" in api_headers["Strict-Transport-Security"]
    assert "geolocation=()" in api_headers["Permissions-Policy"]
    assert api_headers["Cache-Control"] == "no-store"

    static_headers = client.get("/static/app.js").headers
    assert "max-age" in static_headers["Cache-Control"]


def test_request_id_echo_and_sanitization() -> None:
    generated = client.get("/api/health").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/api/health", headers={"X-Request-ID": "trace-12345678"})
    assert echoed.headers["X-Request-ID"] == "trace-12345678"
    bad = client.get("/api/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert bad.headers["X-Request-ID"] != "bad id\twith spaces"


def test_wcag_accessibility_landmarks_and_table() -> None:
    html = client.get("/").text
    assert 'role="main"' in html
    assert 'aria-live="polite"' in html
    assert 'class="skip-link"' in html
    assert 'id="contrast-toggle"' in html
    assert 'class="forecast-table"' in html
    assert 'id="copy-share-btn"' in html


def test_input_validation_and_payload_size_limit() -> None:
    assert client.post("/api/analyze", json={"city": "A"}).status_code == 422
    assert client.post("/api/analyze", json={"city": "x" * 81}).status_code == 422
    bad_prof = {"city": "Jaipur", "profile": "Hacker"}
    assert client.post("/api/analyze", json=bad_prof).status_code == 422
    assert client.post("/api/analyze", json={"city": "Jaipur", "unknown": 1}).status_code == 422

    bad_chars = client.post("/api/analyze", json={"city": "<>;;!"})
    assert bad_chars.status_code == 400
    assert "valid city" in bad_chars.json()["detail"]

    oversized = client.post("/api/analyze", json={"city": "Jaipur", "pad": "x" * 20_000})
    assert oversized.status_code == 413

    header_oversized = client.post(
        "/api/analyze",
        content=b'{"city":"Jaipur"}',
        headers={"Content-Type": "application/json", "Content-Length": "20000"},
    )
    assert header_oversized.status_code == 413


@patch("app.main.fetch_city_location", new_callable=AsyncMock)
def test_city_not_found_and_upstream_failure(mock_loc: AsyncMock) -> None:
    mock_loc.return_value = None
    assert client.post("/api/analyze", json={"city": "UnknownCityXYZ"}).status_code == 404

    mock_loc.side_effect = UpstreamServiceError("boom")
    err = client.post("/api/analyze", json={"city": "Jaipur"})
    assert err.status_code == 502
    assert "temporarily unavailable" in err.json()["detail"]

    mock_loc.side_effect = httpx.ConnectError("down")
    assert client.post("/api/analyze", json={"city": "Jaipur"}).status_code == 502


@patch("app.main.generate_genai_advisory", new_callable=AsyncMock)
@patch("app.main.fetch_air_quality_report", new_callable=AsyncMock)
@patch("app.main.fetch_city_location", new_callable=AsyncMock)
def test_analyze_end_to_end_and_extended_household_payload(
    mock_loc: AsyncMock, mock_report: AsyncMock, mock_advisory: AsyncMock
) -> None:
    mock_loc.return_value = LOCATION
    mock_report.return_value = make_report()
    mock_advisory.return_value = AIAdvisory(
        health="Health guidance",
        commute="Commute guidance",
        urban="Civic guidance",
        source="Test provider",
    )
    res = client.post(
        "/api/analyze",
        json={
            "city": "Jaipur",
            "profile": "Urban Planner",
            "household": {
                "has_children": True,
                "commute_mode": "Petrol Car",
                "commute_distance_km": 12.0,
            },
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["location"]["name"] == "Jaipur"
    assert data["air_quality"]["dominant_pollutant"] == "PM10 (Coarse Dust)"
    assert len(data["air_quality"]["hourly_forecast"]) == 6

    # Backwards-compatible minimal payload works too.
    minimal = client.post("/api/analyze", json={"city": "Jaipur"})
    assert minimal.status_code == 200
    assert minimal.json()["profile"] == "General Citizen"


@patch("app.main.generate_genai_advisory", new_callable=AsyncMock)
@patch("app.main.fetch_air_quality_report", new_callable=AsyncMock)
@patch("app.main.fetch_city_location", new_callable=AsyncMock)
def test_rate_limit_returns_429_json_with_retry_after(
    mock_loc: AsyncMock, mock_report: AsyncMock, mock_advisory: AsyncMock
) -> None:
    mock_loc.return_value = LOCATION
    mock_report.return_value = make_report()
    mock_advisory.return_value = AIAdvisory(health="h", commute="c", urban="u", source="t")
    responses = [client.post("/api/analyze", json={"city": "Jaipur"}) for _ in range(31)]
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert "Too many requests" in limited.json()["detail"]


def test_lifespan_and_facade_helpers() -> None:
    with TestClient(app) as scoped:
        assert hasattr(scoped.app.state, "http_client")
        assert scoped.get("/api/health").status_code == 200
    assert next_hourly_forecast("2026-11-25T10:00", ["2026-11-25T11:00"], [77]) == [77]
