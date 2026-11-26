"""Pydantic request and response schemas for strict validation and API contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SensitivityProfile = Literal[
    "General Citizen",
    "Child / Elderly",
    "Asthma / Respiratory Sensitivity",
    "Outdoor Athlete",
    "Urban Planner",
]

CommuteMode = Literal[
    "Petrol Car",
    "Two-Wheeler",
    "Bus / Metro",
    "Carpool",
    "Walk / Cycle",
    "Work From Home",
]

BudgetTier = Literal["Free / Zero-Cost", "Low-Cost (<1500)", "HEPA Purifier Ready"]


class HouseholdContext(BaseModel):
    """Optional non-identifying household and lifestyle parameters for deeper personalization."""

    model_config = ConfigDict(extra="forbid")

    has_children: bool = Field(default=False, description="Household includes children")
    has_elderly: bool = Field(default=False, description="Household includes older adults")
    has_respiratory_risk: bool = Field(
        default=False, description="Asthma or cardiorespiratory sensitivity in household"
    )
    commute_mode: CommuteMode = Field(default="Petrol Car", description="Primary commute mode")
    commute_distance_km: float = Field(
        default=10.0, ge=0.5, le=120.0, description="One-way commute distance in km"
    )
    budget_tier: BudgetTier = Field(
        default="Low-Cost (<1500)", description="Preferred indoor air intervention budget"
    )
    owns_purifier: bool = Field(default=False, description="Whether household owns a HEPA purifier")
    room_area_sqft: float = Field(
        default=180.0, ge=40.0, le=2000.0, description="Primary living/bedroom floor area in sq ft"
    )


class AdvisoryRequest(BaseModel):
    """Validated user request payload for urban air quality analysis."""

    model_config = ConfigDict(extra="forbid")

    city: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description="Target urban city name",
        examples=["Jaipur", "Delhi"],
    )
    profile: SensitivityProfile = Field(
        default="General Citizen",
        description="Primary user health sensitivity or civic planning role",
    )
    household: HouseholdContext = Field(
        default_factory=HouseholdContext,
        description="Optional household and commute context for tailored recommendations",
    )


class LocationInfo(BaseModel):
    """Resolved geographic coordinates and metadata for a city."""

    name: str
    country: str
    latitude: float
    longitude: float


class PollutantMetrics(BaseModel):
    """Real-time concentrations of key urban air pollutants in ug/m3 (None when unavailable)."""

    pm2_5: float | None = None
    pm10: float | None = None
    no2: float | None = None
    o3: float | None = None
    co: float | None = None
    so2: float | None = None


class ForecastWindow(BaseModel):
    """Summary of a consecutive 2-hour forecast window."""

    start_time: str
    end_time: str
    average_aqi: int
    label: str


class ForecastPoint(BaseModel):
    """Single hourly forecast observation with local timestamp."""

    time: str
    us_aqi: int


class AirQualityReport(BaseModel):
    """Structured US AQI classification, pollutant breakdown, provenance, and forecast."""

    us_aqi: int
    category: str
    risk_level: str
    badge: str
    dominant_pollutant: str
    pollutants: PollutantMetrics
    hourly_forecast: list[int]
    forecast_points: list[ForecastPoint] = Field(default_factory=list)
    best_window: ForecastWindow | None = None
    worst_window: ForecastWindow | None = None
    measurement_time: str | None = None
    timezone: str = "GMT"
    data_source: str = "Open-Meteo CAMS Global Model (modeled estimate, not ground station)"
    is_cached: bool = False


class RoutineStep(BaseModel):
    """Single time-slotted action item in a personalized daily routine."""

    slot: str
    title: str
    action: str
    reason: str


class IndoorHack(BaseModel):
    """Practical indoor air quality intervention tailored to budget and AQI."""

    title: str
    cost_tier: str
    action: str
    why_it_helps: str


class CommuteImpactEstimate(BaseModel):
    """Transparent tailpipe CO2e impact estimate vs. a cleaner commute alternative."""

    current_mode: str
    recommended_mode: str
    one_way_km: float
    daily_co2_saved_kg: float
    annual_co2_saved_kg: float
    uncertainty_band_kg: tuple[float, float]
    factor_citation: str
    exposure_note: str


class IndoorSizingEstimate(BaseModel):
    """Deterministic HEPA CADR room sizing guide (not a measured reduction claim)."""

    room_area_sqft: float
    recommended_cadr_m3h: tuple[int, int]
    target_ach: float
    methodology_note: str


class AIAdvisory(BaseModel):
    """Actionable health, commute, civic, routine, indoor, and impact recommendations."""

    health: str
    commute: str
    urban: str
    why_this_matters: str = ""
    source: str
    daily_routine: list[RoutineStep] = Field(default_factory=list)
    indoor_hacks: list[IndoorHack] = Field(default_factory=list)
    commute_impact: CommuteImpactEstimate | None = None
    indoor_sizing: IndoorSizingEstimate | None = None
    community_share_text: str = ""


class AnalysisResponse(BaseModel):
    """Complete API response payload combining telemetry, deterministic logic, and GenAI."""

    location: LocationInfo
    profile: SensitivityProfile
    air_quality: AirQualityReport
    advisory: AIAdvisory
