"""Unit tests for deterministic decision logic, routines, indoor sizing, and CO2e math."""

import pytest

from app.aqi import classify_us_aqi
from app.decision_engine import (
    build_commute_impact,
    build_deterministic_advisory,
    build_indoor_sizing,
    effective_risk_aqi,
)
from app.models import (
    AirQualityReport,
    ForecastWindow,
    HouseholdContext,
    PollutantMetrics,
    SensitivityProfile,
)


def make_report(aqi: int = 135) -> AirQualityReport:
    meta = classify_us_aqi(aqi)
    return AirQualityReport(
        us_aqi=aqi,
        category=meta["category"],
        risk_level=meta["risk"],
        badge=meta["badge"],
        dominant_pollutant="PM2.5 (Fine Particulates)",
        pollutants=PollutantMetrics(pm2_5=52.0, pm10=95.0, no2=28.0, o3=40.0),
        hourly_forecast=[aqi, max(40, aqi - 25), aqi + 15],
        best_window=ForecastWindow(
            start_time="2026-11-25T13:00",
            end_time="2026-11-25T14:00",
            average_aqi=85,
            label="13:00-15:00",
        ),
        worst_window=ForecastWindow(
            start_time="2026-11-25T20:00",
            end_time="2026-11-25T21:00",
            average_aqi=195,
            label="20:00-22:00",
        ),
    )


def test_sensitive_profiles_receive_conservative_buffer() -> None:
    report = make_report(80)
    assert effective_risk_aqi(report, "General Citizen", HouseholdContext()) == 80
    assert effective_risk_aqi(report, "Child / Elderly", HouseholdContext()) == 115
    assert (
        effective_risk_aqi(report, "General Citizen", HouseholdContext(has_children=True)) == 115
    )


@pytest.mark.parametrize(
    "profile",
    [
        "General Citizen",
        "Child / Elderly",
        "Asthma / Respiratory Sensitivity",
        "Outdoor Athlete",
        "Urban Planner",
    ],
)
def test_profiles_produce_meaningfully_different_guidance(profile: SensitivityProfile) -> None:
    advisory = build_deterministic_advisory("Delhi", profile, make_report(110))
    assert advisory.health
    assert advisory.commute
    assert advisory.urban
    assert len(advisory.daily_routine) == 4
    assert len(advisory.indoor_hacks) >= 3
    assert advisory.source == "Environmental Rules & Decision Engine"


def test_asthma_vs_athlete_vs_planner_differ_at_moderate_and_elevated_aqi() -> None:
    rep = make_report(90)
    athlete = build_deterministic_advisory("Jaipur", "Outdoor Athlete", rep)
    planner = build_deterministic_advisory("Jaipur", "Urban Planner", rep)
    asthma = build_deterministic_advisory("Jaipur", "Asthma / Respiratory Sensitivity", rep)
    assert athlete.health != planner.health
    assert asthma.health != athlete.health
    assert "construction dust" in planner.urban.lower()


def test_high_aqi_two_wheeler_switches_to_enclosed_transit_advice() -> None:
    hh = HouseholdContext(commute_mode="Two-Wheeler", commute_distance_km=12.0)
    rep = make_report(185)
    advisory = build_deterministic_advisory("Delhi", "General Citizen", rep, hh)
    assert "N95/KN95" in advisory.commute
    assert advisory.commute_impact is not None
    assert advisory.commute_impact.recommended_mode == "Bus / Metro"
    assert advisory.commute_impact.daily_co2_saved_kg > 0


def test_commute_impact_math_and_uncertainty_band() -> None:
    hh = HouseholdContext(commute_mode="Petrol Car", commute_distance_km=10.0)
    impact = build_commute_impact(make_report(120), hh)
    # (0.140 - 0.032) * 20 km = 2.16 kg/day; * 240 = 518.4 kg/yr
    assert impact.daily_co2_saved_kg == pytest.approx(2.16)
    assert impact.annual_co2_saved_kg == pytest.approx(518.4)
    assert impact.uncertainty_band_kg == pytest.approx((414.7, 622.1))


def test_indoor_cadr_sizing_and_hepa_tier() -> None:
    hh = HouseholdContext(
        room_area_sqft=200.0, owns_purifier=True, budget_tier="HEPA Purifier Ready"
    )
    sizing = build_indoor_sizing(hh)
    assert sizing.recommended_cadr_m3h[0] < sizing.recommended_cadr_m3h[1]
    advisory = build_deterministic_advisory("Jaipur", "General Citizen", make_report(160), hh)
    titles = [h.title for h in advisory.indoor_hacks]
    assert "True HEPA Room Sizing & Placement" in titles
    assert all(
        "ozone" not in h.action.lower() or "avoid" in h.action.lower()
        for h in advisory.indoor_hacks
    )


def test_community_share_text_contains_no_personal_identifiers() -> None:
    rep = make_report(140)
    sensitive_hh = HouseholdContext(
        has_children=True, has_elderly=True, has_respiratory_risk=True
    )
    sensitive_adv = build_deterministic_advisory(
        "Jaipur", "Asthma / Respiratory Sensitivity", rep, sensitive_hh
    )
    general_adv = build_deterministic_advisory("Jaipur", "General Citizen", rep, HouseholdContext())
    share = sensitive_adv.community_share_text
    assert share == general_adv.community_share_text
    assert "Jaipur" in share
    assert "140" in share
    for forbidden in ("asthma", "respiratory", "children", "elderly"):
        assert forbidden not in share.lower()
    assert "vulnerable neighbors" in share.lower()
    assert "model estimate" in share.lower()
