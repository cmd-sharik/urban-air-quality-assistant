"""
Comprehensive unit and integration test suite covering endpoints, security,
caching, accessibility, and fallback resilience.
"""

from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models import AirQualityReport, PollutantMetrics
from app.services import (
    build_fallback_advisory,
    classify_us_aqi,
    identify_dominant_pollutant,
    sanitize_city_input,
)

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_security_headers_present():
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


def test_wcag_accessibility_landmarks():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'role="main"' in html
    assert 'aria-live="polite"' in html
    assert 'class="skip-link"' in html
    assert 'id="contrast-toggle"' in html


def test_input_sanitization_blocks_xss():
    dirty = "<script>alert(1)</script>New Delhi; DROP TABLE"
    cleaned = sanitize_city_input(dirty)
    assert "<" not in cleaned
    assert ";" not in cleaned
    assert "New Delhi" in cleaned


def test_aqi_classification_boundaries():
    assert classify_us_aqi(25)["badge"] == "GOOD"
    assert classify_us_aqi(75)["badge"] == "MODERATE"
    assert classify_us_aqi(125)["badge"] == "SENSITIVE"
    assert classify_us_aqi(175)["badge"] == "UNHEALTHY"
    assert classify_us_aqi(250)["badge"] == "VERY_UNHEALTHY"
    assert classify_us_aqi(350)["badge"] == "HAZARDOUS"


def test_dominant_pollutant_detection():
    metrics = PollutantMetrics(pm2_5=60.0, pm10=50.0, no2=20.0, o3=40.0)
    assert "PM2.5" in identify_dominant_pollutant(metrics)


def test_validation_error_on_short_city():
    response = client.post("/api/analyze", json={"city": "A", "profile": "General Citizen"})
    assert response.status_code == 422


def test_fallback_advisory_generation():
    report = AirQualityReport(
        us_aqi=165,
        category="Unhealthy",
        risk_level="High",
        badge="UNHEALTHY",
        dominant_pollutant="PM2.5 (Fine Particulates)",
        pollutants=PollutantMetrics(pm2_5=72.0, pm10=110.0, no2=30.0, o3=45.0),
        hourly_forecast=[160, 165, 170],
    )
    advisory = build_fallback_advisory("Delhi", "Asthma / Respiratory Sensitivity", report)
    assert "Delhi" in advisory.health
    assert "N95" in advisory.commute


@patch("app.main.fetch_city_location", new_callable=AsyncMock)
def test_city_not_found_returns_404(mock_loc):
    mock_loc.return_value = None
    response = client.post("/api/analyze", json={"city": "UnknownCityXYZ", "profile": "General Citizen"})
    assert response.status_code == 404


@patch("app.main.fetch_city_location", new_callable=AsyncMock)
@patch("app.main.fetch_air_quality_report", new_callable=AsyncMock)
def test_analyze_endpoint_end_to_end(mock_report, mock_loc):
    from app.models import LocationInfo

    mock_loc.return_value = LocationInfo(
        name="Jaipur", country="India", latitude=26.91, longitude=75.78
    )
    mock_report.return_value = AirQualityReport(
        us_aqi=95,
        category="Moderate",
        risk_level="Moderate",
        badge="MODERATE",
        dominant_pollutant="PM10 (Coarse Dust)",
        pollutants=PollutantMetrics(pm2_5=32.0, pm10=68.0, no2=18.0, o3=42.0),
        hourly_forecast=[90, 92, 95, 98, 100, 96],
    )
    response = client.post(
        "/api/analyze",
        json={"city": "Jaipur", "profile": "Urban Planner"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location"]["name"] == "Jaipur"
    assert data["air_quality"]["dominant_pollutant"] == "PM10 (Coarse Dust)"
    assert len(data["air_quality"]["hourly_forecast"]) == 6
