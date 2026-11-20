"""
Pydantic request and response schemas for strict input validation and API contracts.
"""

from typing import List, Literal
from pydantic import BaseModel, Field

SensitivityProfile = Literal[
    "General Citizen",
    "Child / Elderly",
    "Asthma / Respiratory Sensitivity",
    "Outdoor Athlete",
    "Urban Planner",
]


class AdvisoryRequest(BaseModel):
    """Validated user request payload for air quality analysis."""

    city: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description="Target urban city name",
        examples=["Jaipur", "Delhi"],
    )
    profile: SensitivityProfile = Field(
        default="General Citizen",
        description="User health sensitivity or civic planning role",
    )


class LocationInfo(BaseModel):
    """Resolved geographic coordinates and metadata for a city."""

    name: str
    country: str
    latitude: float
    longitude: float


class PollutantMetrics(BaseModel):
    """Real-time concentrations of key urban air pollutants in µg/m³."""

    pm2_5: float
    pm10: float
    no2: float
    o3: float


class AirQualityReport(BaseModel):
    """Structured US AQI classification, pollutant breakdown, and short-term forecast."""

    us_aqi: int
    category: str
    risk_level: str
    badge: str
    dominant_pollutant: str
    pollutants: PollutantMetrics
    hourly_forecast: List[int]


class AIAdvisory(BaseModel):
    """Actionable health, commute, and civic recommendations."""

    health: str
    commute: str
    urban: str
    source: str


class AnalysisResponse(BaseModel):
    """Complete API response payload combining telemetry and GenAI guidance."""

    location: LocationInfo
    profile: SensitivityProfile
    air_quality: AirQualityReport
    advisory: AIAdvisory
