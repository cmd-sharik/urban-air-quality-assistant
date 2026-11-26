"""Contract tests for Open-Meteo geocoding, telemetry validation, and caching."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.telemetry import (
    AQI_CACHE,
    GEO_CACHE,
    UpstreamServiceError,
    fetch_air_quality_report,
    fetch_city_location,
)


def http_response(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data, request=httpx.Request("GET", "https://example.com"))


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    GEO_CACHE.clear()
    AQI_CACHE.clear()


@pytest.mark.asyncio
async def test_geocoding_caches_and_handles_missing_city() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = http_response(
        {"results": [{"name": "Jaipur", "country": "India", "latitude": 26.91, "longitude": 75.78}]}
    )
    first = await fetch_city_location("Jaipur", client)
    second = await fetch_city_location("Jaipur", client)
    assert first == second
    assert first is not None
    assert first.name == "Jaipur"
    client.get.assert_awaited_once()

    client.get.reset_mock()
    client.get.return_value = http_response({})
    assert await fetch_city_location("Nowhereville", client) is None


@pytest.mark.asyncio
async def test_geocoding_rejects_malformed_payload() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = http_response({"results": [{"name": "Bad"}]})
    with pytest.raises(UpstreamServiceError):
        await fetch_city_location("BadCity", client)

    client.get.side_effect = httpx.ConnectError("down")
    with pytest.raises(UpstreamServiceError):
        await fetch_city_location("DownCity", client)


@pytest.mark.asyncio
async def test_air_quality_handles_optional_pollutants_and_caching() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = http_response(
        {
            "timezone": "Asia/Kolkata",
            "current": {
                "time": "2026-11-25T10:00",
                "us_aqi": 115,
                "pm2_5": 42.0,
                "pm10": None,
                "nitrogen_dioxide": 22.0,
                "ozone": None,
            },
            "hourly": {
                "time": ["2026-11-25T11:00", "2026-11-25T12:00"],
                "us_aqi": [95, 85],
            },
        }
    )
    first = await fetch_air_quality_report(26.91, 75.78, client)
    second = await fetch_air_quality_report(26.91, 75.78, client)
    assert first.is_cached is False
    assert second.is_cached is True
    assert first.us_aqi == 115
    assert first.pollutants.pm10 is None
    assert first.pollutants.o3 is None
    assert first.timezone == "Asia/Kolkata"
    assert first.hourly_forecast == [95, 85]
    assert first.best_window is not None
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_air_quality_rejects_missing_us_aqi_and_http_errors() -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = http_response({"current": {"us_aqi": None}})
    with pytest.raises(UpstreamServiceError):
        await fetch_air_quality_report(10.0, 20.0, client)

    client.get.return_value = http_response({}, status=500)
    with pytest.raises(UpstreamServiceError):
        await fetch_air_quality_report(11.0, 21.0, client)
