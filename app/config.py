"""Application configuration, environmental thresholds, and emission factors."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AQIBand:
    """US EPA AQI classification threshold band."""

    max_aqi: int
    category: str
    risk_level: str
    badge: str


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment variables."""

    app_title: str = "Urban Air Quality Assistant"
    app_version: str = "3.0.0"
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    allowed_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
        if origin.strip()
    )
    geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    gemini_url_template: str = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )
    geo_cache_ttl: int = 86400
    aqi_cache_ttl: int = 900
    http_timeout: float = 8.0
    gemini_timeout: float = 10.0
    max_request_bytes: int = 16_384

    @property
    def gemini_url(self) -> str:
        """Build the configured Gemini endpoint URL."""
        return self.gemini_url_template.format(model=self.gemini_model)


settings = Settings()

# US EPA AQI breakpoints (explicitly labeled as US AQI, not Indian NAQI).
AQI_BANDS: tuple[AQIBand, ...] = (
    AQIBand(50, "Good", "Low", "GOOD"),
    AQIBand(100, "Moderate", "Moderate", "MODERATE"),
    AQIBand(150, "Unhealthy for Sensitive Groups", "Elevated", "SENSITIVE"),
    AQIBand(200, "Unhealthy", "High", "UNHEALTHY"),
    AQIBand(300, "Very Unhealthy", "Very High", "VERY_UNHEALTHY"),
    AQIBand(10_000, "Hazardous", "Severe", "HAZARDOUS"),
)

# WHO 2021 Global Air Quality Guideline 24h (or 8h peak for O3) thresholds in ug/m3.
WHO_THRESHOLDS: dict[str, tuple[str, float]] = {
    "pm2_5": ("PM2.5 (Fine Particulates)", 15.0),
    "pm10": ("PM10 (Coarse Dust)", 45.0),
    "no2": ("NO\u2082 (Traffic Emissions)", 25.0),
    "o3": ("O\u2083 (Ground Ozone)", 100.0),
}

# Illustrative passenger-km tailpipe CO2e factors (kg CO2e/km) for urban India,
# adapted from India GHG Program / ICCT / TERI published fleet averages (+/-20% planning band).
COMMUTE_CO2_KG_PER_KM: dict[str, float] = {
    "Petrol Car": 0.140,
    "Two-Wheeler": 0.040,
    "Bus / Metro": 0.032,
    "Carpool": 0.047,
    "Walk / Cycle": 0.000,
    "Work From Home": 0.000,
}

# Workdays per year used for annualized commute estimates.
ANNUAL_COMMUTE_DAYS = 240
EMISSION_UNCERTAINTY_RATIO = 0.20
