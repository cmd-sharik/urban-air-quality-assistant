"""Unit tests for Gemini integration, structured parsing, safety rules, and fallbacks."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.ai_advisor import generate_genai_advisory, is_safe_ai_text, parse_gemini_advisory
from app.aqi import classify_us_aqi
from app.models import AirQualityReport, PollutantMetrics


def make_report(aqi: int = 120) -> AirQualityReport:
    meta = classify_us_aqi(aqi)
    return AirQualityReport(
        us_aqi=aqi,
        category=meta["category"],
        risk_level=meta["risk"],
        badge=meta["badge"],
        dominant_pollutant="PM2.5 (Fine Particulates)",
        pollutants=PollutantMetrics(pm2_5=48.0, pm10=70.0, no2=20.0, o3=35.0),
        hourly_forecast=[aqi],
    )


def gemini_payload(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
        request=httpx.Request("POST", "https://example.com/gemini"),
    )


def test_parser_handles_json_fenced_json_and_legacy_lines() -> None:
    raw_json = json.dumps(
        {
            "health": "Limit prolonged runs.",
            "commute": "Use enclosed metro.",
            "urban": "Enforce dust barriers.",
            "why_this_matters": "PM2.5 is elevated.",
        }
    )
    parsed = parse_gemini_advisory(raw_json, "PM2.5", aqi=120)
    assert parsed is not None
    assert parsed.health == "Limit prolonged runs."
    assert parsed.why_this_matters == "PM2.5 is elevated."

    fenced = parse_gemini_advisory(f"```json\n{raw_json}\n```", "PM2.5", aqi=120)
    assert fenced is not None
    assert fenced.commute == "Use enclosed metro."

    prefixed = parse_gemini_advisory(f"Advisory:\n{raw_json}\nDone.", "PM2.5", aqi=120)
    assert prefixed is not None
    assert prefixed.urban == "Enforce dust barriers."

    legacy = parse_gemini_advisory(
        "OTHER: skip\n**HEALTH:** Stay indoors\n**COMMUTE:** Use metro", "PM10", aqi=120
    )
    assert legacy is not None
    assert "PM10" in legacy.urban


def test_parser_rejects_incomplete_or_malformed_output() -> None:
    assert parse_gemini_advisory("", "PM2.5") is None
    assert parse_gemini_advisory("{bad json", "PM2.5") is None
    assert parse_gemini_advisory("HEALTH: Only health line", "PM2.5") is None
    assert parse_gemini_advisory("[1, 2, 3]", "PM2.5") is None


@pytest.mark.parametrize(
    ("text", "aqi", "expected"),
    [
        ("Run an ozone generator overnight.", 120, False),
        ("Avoid any ozone generator in bedrooms.", 120, True),
        ("This cures asthma and prescribes 50mg dosage of steroids.", 120, False),
        ("Cuts indoor PM2.5 by 87% instantly.", 120, False),
        ("Reduces 87% of indoor air pollution.", 120, False),
        ("Lowers PM 10 exposure by 42.5% today.", 120, False),
        ("65% drop in particulate concentration guaranteed.", 120, False),
        ("Never expect indoor air to improve by 50% from curtains alone.", 120, True),
        ("Humidity is 65% today; wear a 95% rated N95 mask outdoors.", 120, True),
        ("Click https://evil.example for tips.", 80, False),
        ("Open windows wide all afternoon.", 160, False),
        ("Keep windows closed unless the cleaner forecast window arrives.", 160, True),
        ("Open windows briefly during the cleaner forecast window.", 140, True),
        ("Open windows for fresh morning air.", 45, True),
    ],
)
def test_ai_safety_guardrails(text: str, aqi: int, expected: bool) -> None:
    assert is_safe_ai_text(text, aqi) is expected


@pytest.mark.asyncio
async def test_missing_or_placeholder_key_uses_deterministic_engine() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    for key in ("", "your_google_gemini_api_key_here"):
        with patch("app.ai_advisor.settings") as cfg:
            cfg.gemini_api_key = key
            result = await generate_genai_advisory(
                "Jaipur", "General Citizen", make_report(), mock_client
            )
        assert result.source == "Environmental Rules & Decision Engine"
        assert len(result.daily_routine) == 4
        mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_success_uses_header_and_preserves_deterministic_modules() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = gemini_payload(
        json.dumps(
            {
                "health": "Keep kids indoors during rush hour.",
                "commute": "Take metro instead of scooter.",
                "urban": "Water dusty arterial roads.",
                "why_this_matters": "PM2.5 exceeds WHO 24h levels.",
            }
        )
    )
    with patch("app.ai_advisor.settings") as cfg:
        cfg.gemini_api_key = "real-key"
        cfg.gemini_url = "https://example.com/gemini"
        cfg.gemini_timeout = 10.0
        result = await generate_genai_advisory(
            "Jaipur", "Child / Elderly", make_report(), mock_client
        )
    assert result.source == "Google Gemini 2.5 Flash"
    assert result.health == "Keep kids indoors during rush hour."
    assert len(result.daily_routine) == 4
    assert result.commute_impact is not None
    kwargs = mock_client.post.await_args.kwargs
    assert kwargs["headers"]["x-goog-api-key"] == "real-key"
    assert "params" not in kwargs


@pytest.mark.asyncio
async def test_gemini_retries_once_on_503_and_falls_back_on_persistent_error() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [
        gemini_payload("{}", status=503),
        gemini_payload(
            json.dumps(
                {
                    "health": "Recovered after retry.",
                    "commute": "Use N95 mask.",
                    "urban": "Reduce idling.",
                    "why_this_matters": "Smog risk elevated.",
                }
            )
        ),
    ]
    with patch("app.ai_advisor.settings") as cfg:
        cfg.gemini_api_key = "real-key"
        cfg.gemini_url = "https://example.com/gemini"
        cfg.gemini_timeout = 10.0
        recovered = await generate_genai_advisory(
            "Jaipur", "General Citizen", make_report(), mock_client
        )
    assert recovered.source == "Google Gemini 2.5 Flash"
    assert recovered.health == "Recovered after retry."
    assert mock_client.post.await_count == 2

    mock_client.post.reset_mock()
    mock_client.post.side_effect = httpx.ConnectError("down")
    with patch("app.ai_advisor.settings") as cfg:
        cfg.gemini_api_key = "real-key"
        cfg.gemini_url = "https://example.com/gemini"
        cfg.gemini_timeout = 10.0
        fallback = await generate_genai_advisory(
            "Jaipur", "General Citizen", make_report(), mock_client
        )
    assert fallback.source == "Environmental Rules & Decision Engine"


@pytest.mark.asyncio
async def test_gemini_unsafe_response_falls_back() -> None:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = gemini_payload(
        json.dumps(
            {
                "health": "Use an ozone generator for your bedroom.",
                "commute": "Drive alone.",
                "urban": "None.",
                "why_this_matters": "Bad advice.",
            }
        )
    )
    with patch("app.ai_advisor.settings") as cfg:
        cfg.gemini_api_key = "real-key"
        cfg.gemini_url = "https://example.com/gemini"
        cfg.gemini_timeout = 10.0
        result = await generate_genai_advisory(
            "Jaipur", "General Citizen", make_report(), mock_client
        )
    assert result.source == "Environmental Rules & Decision Engine"
