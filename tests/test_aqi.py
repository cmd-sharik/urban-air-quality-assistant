"""Unit tests for pure AQI classification, validation, dominance, and forecast windowing."""

import pytest

from app.aqi import (
    classify_us_aqi,
    find_forecast_windows,
    identify_dominant_pollutant,
    next_hourly_forecast_points,
    optional_measurement,
    sanitize_city_input,
    valid_measurement,
)
from app.models import ForecastPoint, PollutantMetrics


@pytest.mark.parametrize("city", ["जयपुर", "São Paulo", "Zürich", "New Delhi"])
def test_sanitize_preserves_unicode_city_names(city: str) -> None:
    assert sanitize_city_input(city) == city


def test_sanitize_strips_markup_and_collapses_whitespace() -> None:
    dirty = "<script>alert(1)</script>New Delhi; DROP TABLE"
    cleaned = sanitize_city_input(dirty)
    assert "<" not in cleaned
    assert ";" not in cleaned
    assert "New Delhi" in cleaned
    assert len(sanitize_city_input("a" * 200)) == 80


@pytest.mark.parametrize(
    ("aqi", "badge"),
    [
        (0, "GOOD"),
        (50, "GOOD"),
        (51, "MODERATE"),
        (100, "MODERATE"),
        (101, "SENSITIVE"),
        (150, "SENSITIVE"),
        (151, "UNHEALTHY"),
        (200, "UNHEALTHY"),
        (201, "VERY_UNHEALTHY"),
        (300, "VERY_UNHEALTHY"),
        (301, "HAZARDOUS"),
        (99999, "HAZARDOUS"),
    ],
)
def test_aqi_classification_boundaries(aqi: int, badge: str) -> None:
    assert classify_us_aqi(aqi)["badge"] == badge


@pytest.mark.parametrize("value", [None, True, False, -1, float("nan"), float("inf"), "40"])
def test_invalid_measurement_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        valid_measurement(value)


def test_zero_and_optional_measurements() -> None:
    assert valid_measurement(0) == 0.0
    assert optional_measurement(None) is None
    assert optional_measurement("bad") is None
    assert optional_measurement(12.345) == 12.3


@pytest.mark.parametrize(
    ("metrics", "expected_token"),
    [
        (PollutantMetrics(pm2_5=60.0, pm10=50.0, no2=20.0, o3=40.0), "PM2.5"),
        (PollutantMetrics(pm2_5=1.0, pm10=100.0, no2=1.0, o3=1.0), "PM10"),
        (PollutantMetrics(pm2_5=1.0, pm10=1.0, no2=90.0, o3=1.0), "NO₂"),
        (PollutantMetrics(pm2_5=1.0, pm10=1.0, no2=1.0, o3=300.0), "O₃"),
        (PollutantMetrics(pm2_5=None, pm10=None, no2=None, o3=None), "Primary Metric"),
    ],
)
def test_dominant_pollutant_variants(metrics: PollutantMetrics, expected_token: str) -> None:
    assert expected_token in identify_dominant_pollutant(metrics)


def test_forecast_crosses_midnight_chronologically() -> None:
    points = next_hourly_forecast_points(
        "2026-11-24T23:15",
        ["2026-11-24T00:00", "2026-11-25T00:00:00", "2026-11-25T01:00"],
        [5, 90, 100],
    )
    assert [(p.time, p.us_aqi) for p in points] == [
        ("2026-11-25T00:00", 90),
        ("2026-11-25T01:00", 100),
    ]


def test_forecast_stops_at_missing_hour_without_fabricating() -> None:
    points = next_hourly_forecast_points(
        "2026-11-24T10:00",
        ["2026-11-24T11:00", "2026-11-24T12:00", "2026-11-24T13:00"],
        [80, None, 60],
    )
    assert [p.us_aqi for p in points] == [80]
    assert next_hourly_forecast_points("bad-time", [], []) == []
    assert next_hourly_forecast_points("2026-11-24T10:00", None, None) == []


def test_forecast_windows_cleanest_and_worst() -> None:
    pts = [
        ForecastPoint(time="2026-11-25T10:00", us_aqi=140),
        ForecastPoint(time="2026-11-25T11:00", us_aqi=80),
        ForecastPoint(time="2026-11-25T12:00", us_aqi=70),
        ForecastPoint(time="2026-11-25T13:00", us_aqi=190),
    ]
    best, worst = find_forecast_windows(pts, current_aqi=150)
    assert best is not None
    assert best.label == "11:00-13:00"
    assert best.average_aqi == 75
    assert worst is not None
    assert worst.label == "12:00-14:00"


def test_forecast_windows_suppresses_best_when_worse_than_high_current() -> None:
    pts = [
        ForecastPoint(time="2026-11-25T10:00", us_aqi=160),
        ForecastPoint(time="2026-11-25T11:00", us_aqi=180),
    ]
    best, worst = find_forecast_windows(pts, current_aqi=130)
    assert best is None
    assert worst is not None
    assert find_forecast_windows(pts[:1], current_aqi=130) == (None, None)
