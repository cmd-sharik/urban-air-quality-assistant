from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app, classify_aqi, sanitize_text

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}


def test_wcag_accessibility_landmarks():
    res = client.get("/")
    assert res.status_code == 200
    assert 'role="main"' in res.text
    assert 'aria-live="polite"' in res.text
    assert 'class="skip-link"' in res.text


def test_security_sanitization():
    assert "<" not in sanitize_text("<script>Delhi</script>")


def test_aqi_levels():
    assert classify_aqi(30)["badge"] == "GOOD"
    assert classify_aqi(180)["badge"] == "UNHEALTHY"


def test_input_validation():
    res = client.post("/api/analyze", json={"city": "X", "profile": "General Citizen"})
    assert res.status_code == 422


@patch("app.main.get_coordinates", new_callable=AsyncMock)
@patch("app.main.get_aqi_data", new_callable=AsyncMock)
def test_analyze_flow(mock_aqi, mock_geo):
    mock_geo.return_value = {"name": "Jaipur", "country": "India", "latitude": 26.91, "longitude": 75.78}
    mock_aqi.return_value = {
        "us_aqi": 95,
        "category": "Moderate",
        "risk_level": "Moderate",
        "badge": "MODERATE",
        "pollutants": {"pm2_5": 32.0, "pm10": 60.0, "no2": 18.0, "o3": 40.0},
    }
    res = client.post("/api/analyze", json={"city": "Jaipur", "profile": "General Citizen"})
    assert res.status_code == 200
    assert res.json()["location"]["name"] == "Jaipur"
