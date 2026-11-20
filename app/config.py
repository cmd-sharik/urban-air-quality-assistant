"""
Application configuration and external service constants.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from environment variables."""

    app_title: str = "Urban Air Quality Assistant"
    app_version: str = "2.0.0"
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    allowed_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    )
    geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    gemini_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
    )
    geo_cache_ttl: int = 86400
    aqi_cache_ttl: int = 900
    http_timeout: float = 8.0


settings = Settings()
