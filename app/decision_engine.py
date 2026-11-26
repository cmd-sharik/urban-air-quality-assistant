"""Deterministic household, routine, indoor air, commute impact, and community engine."""

from app.config import ANNUAL_COMMUTE_DAYS, COMMUTE_CO2_KG_PER_KM, EMISSION_UNCERTAINTY_RATIO
from app.models import (
    AIAdvisory,
    AirQualityReport,
    CommuteImpactEstimate,
    HouseholdContext,
    IndoorHack,
    IndoorSizingEstimate,
    RoutineStep,
    SensitivityProfile,
)

_SENSITIVE_PROFILES: frozenset[str] = frozenset(
    {"Child / Elderly", "Asthma / Respiratory Sensitivity"}
)
_SQFT_TO_SQM = 0.092903
_DEFAULT_CEILING_M = 2.74


def _is_sensitive_context(profile: SensitivityProfile, hh: HouseholdContext) -> bool:
    """Return True when the primary profile or household includes sensitive groups."""
    return (
        profile in _SENSITIVE_PROFILES
        or hh.has_children
        or hh.has_elderly
        or hh.has_respiratory_risk
    )


def effective_risk_aqi(
    report: AirQualityReport, profile: SensitivityProfile, hh: HouseholdContext
) -> int:
    """Compute effective AQI tier with conservative +35 buffer for sensitive groups."""
    return report.us_aqi + 35 if _is_sensitive_context(profile, hh) else report.us_aqi


def _moderate_health_guidance(
    city: str, profile: SensitivityProfile, aqi: int, dominant: str
) -> str:
    """Generate profile-differentiated health advice for moderate effective AQI (51-100)."""
    if profile == "Outdoor Athlete":
        return (
            f"Moderate air in {city} (US AQI {aqi}, {dominant}). Shift high-intensity intervals "
            "away from main roads and monitor breathing comfort."
        )
    if profile == "Urban Planner":
        return (
            f"Moderate baseline in {city} (US AQI {aqi}, {dominant}). Prioritize preventive "
            "dust suppression and school-zone traffic calming before evening inversions."
        )
    return (
        f"Moderate air in {city} (US AQI {aqi}, {dominant}). Most activities are safe; "
        f"{profile} users should pace prolonged outdoor exertion."
    )


def _elevated_health_guidance(
    city: str,
    profile: SensitivityProfile,
    hh: HouseholdContext,
    aqi: int,
    dominant: str,
) -> str:
    """Generate profile-differentiated health advice for elevated effective AQI (101-150)."""
    if _is_sensitive_context(profile, hh):
        return (
            f"Elevated risk for sensitive groups in {city} (US AQI {aqi}, {dominant}). "
            "Move children's play and senior walks indoors; keep rescue inhalers accessible."
        )
    if profile == "Outdoor Athlete":
        return (
            f"Elevated pollution in {city} (US AQI {aqi}, {dominant}). Swap prolonged outdoor "
            "cardio for indoor training or shorter low-intensity sessions."
        )
    return (
        f"Elevated pollution in {city} (US AQI {aqi}, {dominant}). Shorten strenuous outdoor "
        "errands and favor the cleaner forecast window."
    )


def _profile_health_guidance(
    city: str,
    profile: SensitivityProfile,
    report: AirQualityReport,
    hh: HouseholdContext,
) -> str:
    """Generate differentiated deterministic health guidance by sensitivity and AQI."""
    aqi = report.us_aqi
    eff = effective_risk_aqi(report, profile, hh)
    dominant = report.dominant_pollutant

    if eff <= 50:
        return (
            f"Clean modeled air in {city} (US AQI {aqi}). Safe for normal outdoor exercise, "
            "school play, and natural cross-ventilation."
        )
    if eff <= 100:
        return _moderate_health_guidance(city, profile, aqi, dominant)
    if eff <= 150:
        return _elevated_health_guidance(city, profile, hh, aqi, dominant)
    return (
        f"Unhealthy winter smog alert in {city} (US AQI {aqi}, {dominant}). Avoid outdoor "
        "exertion, keep windows sealed against smog ingress, and protect vulnerable members."
    )


def _commute_guidance(report: AirQualityReport, hh: HouseholdContext) -> str:
    """Generate practical commute and mask guidance tailored to mode and AQI."""
    aqi = report.us_aqi
    mode = hh.commute_mode
    if aqi <= 50:
        return (
            f"Low-exposure conditions for {mode}. Walking, cycling, and open-window transit "
            "carry minimal particulate burden today."
        )
    if aqi <= 100:
        if mode in {"Walk / Cycle", "Two-Wheeler"}:
            return (
                f"For {mode}, choose quieter residential streets away from diesel corridors "
                "during peak traffic hours."
            )
        return (
            f"Standard commuting via {mode}; consider shifting flexible trips to cleaner hours "
            "and keeping cabin air recirculated in congestion."
        )
    if mode in {"Walk / Cycle", "Two-Wheeler"}:
        return (
            f"High particulate alert (US AQI {aqi}) makes unshielded {mode} high-exposure. "
            "Switch to enclosed metro/bus if feasible, or wear a well-fitted N95/KN95 respirator."
        )
    enclosed = "Metro/Bus" if mode == "Bus / Metro" else "recirculated cabin or Metro"
    return (
        f"Use enclosed transit ({enclosed}) with a well-fitted N95/KN95 mask outdoors; "
        "avoid peak rush-hour idling."
    )


def _urban_guidance(report: AirQualityReport, profile: SensitivityProfile) -> str:
    """Generate civic or community mitigation focus targeting the dominant pollutant."""
    dominant = report.dominant_pollutant
    if profile == "Urban Planner":
        return (
            f"Target {dominant} via construction dust containment, mechanized wet road sweeping, "
            "signal green-waves, and neighborhood open-burning enforcement."
        )
    return (
        f"Reduce community {dominant} buildup by avoiding leaf/waste burning, eliminating vehicle "
        "idling near schools, and shifting short car trips to shared or transit options."
    )


def build_indoor_sizing(hh: HouseholdContext) -> IndoorSizingEstimate:
    """Compute transparent HEPA CADR room sizing without fabricating indoor reductions."""
    volume_m3 = hh.room_area_sqft * _SQFT_TO_SQM * _DEFAULT_CEILING_M
    low_ach, high_ach = 4.0, 5.0
    cadr_low = max(40, round(volume_m3 * low_ach))
    cadr_high = max(cadr_low + 20, round(volume_m3 * high_ach))
    return IndoorSizingEstimate(
        room_area_sqft=round(hh.room_area_sqft, 1),
        recommended_cadr_m3h=(cadr_low, cadr_high),
        target_ach=low_ach,
        methodology_note=(
            f"Sizing formula: floor area ({hh.room_area_sqft:.0f} sq ft) x 2.74 m ceiling "
            "x 4-5 ACH. Verify rated CADR on certified HEPA units; sizing does not guarantee "
            "a specific % indoor reduction."
        ),
    )


def build_commute_impact(report: AirQualityReport, hh: HouseholdContext) -> CommuteImpactEstimate:
    """Estimate tailpipe CO2e savings of shifting to a lower-emission practical alternative."""
    current = hh.commute_mode
    if current in {"Walk / Cycle", "Work From Home"}:
        recommended = current
    elif current == "Petrol Car":
        recommended = "Bus / Metro"
    elif current == "Two-Wheeler":
        recommended = "Bus / Metro" if report.us_aqi > 150 else "Walk / Cycle"
    else:
        recommended = "Work From Home" if report.us_aqi > 200 else "Bus / Metro"

    cur_factor = COMMUTE_CO2_KG_PER_KM.get(current, 0.140)
    rec_factor = COMMUTE_CO2_KG_PER_KM.get(recommended, cur_factor)
    delta_per_km = max(0.0, cur_factor - rec_factor)
    round_trip_km = hh.commute_distance_km * 2.0
    daily_saved = round(delta_per_km * round_trip_km, 2)
    annual_saved = round(daily_saved * ANNUAL_COMMUTE_DAYS, 1)
    band_low = round(annual_saved * (1.0 - EMISSION_UNCERTAINTY_RATIO), 1)
    band_high = round(annual_saved * (1.0 + EMISSION_UNCERTAINTY_RATIO), 1)

    exposure_note = (
        "High outdoor AQI (>150) favors enclosed metro/bus or WFH over unmasked walking/cycling "
        "to avoid elevated particulate inhalation."
        if report.us_aqi > 150
        else "Shorter roadside duration lowers concentration x time exposure; not a clinical score."
    )
    return CommuteImpactEstimate(
        current_mode=current,
        recommended_mode=recommended,
        one_way_km=hh.commute_distance_km,
        daily_co2_saved_kg=daily_saved,
        annual_co2_saved_kg=annual_saved,
        uncertainty_band_kg=(band_low, band_high),
        factor_citation=(
            f"Tailpipe CO2e only: {current} ({cur_factor:.3f} kg/km) vs {recommended} "
            f"({rec_factor:.3f} kg/km), India GHG/ICCT/TERI averages, 240 days/yr (+/-20%)."
        ),
        exposure_note=exposure_note,
    )


def _morning_and_commute_steps(
    report: AirQualityReport,
    hh: HouseholdContext,
    elevated: bool,
    best_lbl: str,
    worst_lbl: str,
) -> tuple[RoutineStep, RoutineStep]:
    """Construct morning ventilation and commute timing routine steps."""
    morning_action = (
        f"Keep exterior windows closed during morning inversion; ventilate briefly only if "
        f"the cleaner window ({best_lbl}) drops into safe range."
        if elevated
        else f"Open cross-windows for 15-20 minutes during {best_lbl} to refresh indoor air."
    )
    high_open_mode = report.us_aqi > 150 and hh.commute_mode in {"Two-Wheeler", "Walk / Cycle"}
    mode_tip = (
        "use enclosed metro/bus or carpool rather than open two-wheeler."
        if high_open_mode
        else f"shift flexible {hh.commute_mode} trips toward {best_lbl}."
    )
    return (
        RoutineStep(
            slot="Morning",
            title="Seal vs. Ventilate Timing",
            action=morning_action,
            reason="Winter thermal inversions trap particulates near ground level after sunrise.",
        ),
        RoutineStep(
            slot="Commute",
            title="Low-Emission Travel Window",
            action=f"Batch errands and avoid congested corridors during {worst_lbl}; {mode_tip}",
            reason="Cutting roadside dwell time and idling reduces exposure and emissions.",
        ),
    )


def build_daily_routine(
    report: AirQualityReport, profile: SensitivityProfile, hh: HouseholdContext
) -> list[RoutineStep]:
    """Build time-slotted daily routine anchored to forecast windows and household profile."""
    eff = effective_risk_aqi(report, profile, hh)
    best_lbl = report.best_window.label if report.best_window else "midday if haze clears"
    worst_lbl = report.worst_window.label if report.worst_window else "evening peak inversion"
    morning_step, commute_step = _morning_and_commute_steps(
        report, hh, eff > 100, best_lbl, worst_lbl
    )
    household_action = (
        "Schedule indoor play and keep school-run drop-offs brisk at gates with zero idling."
        if hh.has_children or profile == "Child / Elderly"
        else "Keep outdoor exertion moderate and avoid heavy roadside exercise."
    )
    evening_action = (
        f"Seal doors/windows before {worst_lbl}, run kitchen exhaust during cooking, "
        "and avoid burning incense, candles, or outdoor waste."
    )
    return [
        morning_step,
        commute_step,
        RoutineStep(
            slot="Family / Activity",
            title="Exposure-Aware Scheduling",
            action=household_action,
            reason="Sensitive lungs absorb higher particulate loads per breath during smog.",
        ),
        RoutineStep(
            slot="Evening / Night",
            title="Clean-Air Sleep Zone",
            action=evening_action,
            reason="Evening cooling re-intensifies smog; indoor combustion compounds PM2.5.",
        ),
    ]


def _tier_specific_indoor_hack(hh: HouseholdContext, sizing: IndoorSizingEstimate) -> IndoorHack:
    """Select the budget-appropriate purifier or clean-room anchor hack."""
    cadr_low, cadr_high = sizing.recommended_cadr_m3h
    if hh.owns_purifier or hh.budget_tier == "HEPA Purifier Ready":
        return IndoorHack(
            title="True HEPA Room Sizing & Placement",
            cost_tier="HEPA Purifier Ready",
            action=(
                f"Target a certified True HEPA purifier rated {cadr_low}-{cadr_high} m3/h CADR "
                f"for your {hh.room_area_sqft:.0f} sq ft room; avoid ozone/ioniser modes."
            ),
            why_it_helps="Maintains 4-5 air changes/hour in a closed room without ozone.",
        )
    return IndoorHack(
        title="Clean-Room Anchor & Mask Hygiene",
        cost_tier="Low-Cost (<1500)",
        action=(
            "Designate one low-traffic bedroom for vulnerable family members, damp-wipe "
            "hard surfaces, and keep N95/KN95 masks ready for outdoor trips."
        ),
        why_it_helps="Concentrates limited sealing effort where family members sleep.",
    )


def build_indoor_hacks(report: AirQualityReport, hh: HouseholdContext) -> list[IndoorHack]:
    """Generate safe, budget-tiered indoor air quality hacks (never ozone or blind airing)."""
    sizing = build_indoor_sizing(hh)
    sealing_action = (
        f"Keep windows closed when outdoor US AQI exceeds 100 (currently {report.us_aqi}); "
        "seal bedroom door gaps with a rolled damp towel during peak smog hours."
        if report.us_aqi > 100
        else "Ventilate briefly during low-traffic hours and seal gaps during rush-hour spikes."
    )
    return [
        IndoorHack(
            title="Source-Control & Wet Mopping",
            cost_tier="Free / Zero-Cost",
            action=(
                "Wet-mop floors instead of dry sweeping, run kitchen exhaust while cooking, "
                "and eliminate indoor incense, mosquito coils, and tobacco smoke."
            ),
            why_it_helps="Prevents resuspending settled PM10/PM2.5 and cuts combustion peaks.",
        ),
        IndoorHack(
            title="Targeted Window Sealing & Draft Blocking",
            cost_tier="Free / Zero-Cost",
            action=sealing_action,
            why_it_helps="Reduces outdoor winter smog infiltration into sleeping spaces.",
        ),
        _tier_specific_indoor_hack(hh, sizing),
    ]


def build_community_share_text(
    city: str, report: AirQualityReport, best_label: str | None, worst_label: str | None
) -> str:
    """Create a privacy-safe neighborhood/family alert with zero personal data."""
    window_part = (
        f"Cleaner window: {best_label}. "
        if best_label
        else "No cleaner outdoor window detected yet. "
    )
    peak_part = f"Peak smog window: {worst_label}. " if worst_label else ""
    return (
        f"Air Quality Update - {city}: Modeled US AQI {report.us_aqi} ({report.category}), "
        f"primary driver {report.dominant_pollutant}. {window_part}{peak_part}"
        "Community steps: avoid leaf/trash burning, skip engine idling near schools, and check "
        "on vulnerable neighbors. "
        "(Source: Open-Meteo CAMS model estimate, not a ground station.)"
    )


def build_deterministic_advisory(
    city: str,
    profile: SensitivityProfile,
    report: AirQualityReport,
    household: HouseholdContext | None = None,
) -> AIAdvisory:
    """Build complete, consistent deterministic advisory combining all modules."""
    hh = household or HouseholdContext()
    best_lbl = report.best_window.label if report.best_window else None
    worst_lbl = report.worst_window.label if report.worst_window else None
    impact = build_commute_impact(report, hh)
    sizing = build_indoor_sizing(hh)

    why_summary = (
        f"Modeled US AQI in {city} is {report.us_aqi} ({report.category}), driven by "
        f"{report.dominant_pollutant}. Recommendations adapt to {profile} and {hh.commute_mode}."
    )
    return AIAdvisory(
        health=_profile_health_guidance(city, profile, report, hh),
        commute=_commute_guidance(report, hh),
        urban=_urban_guidance(report, profile),
        why_this_matters=why_summary,
        source="Environmental Rules & Decision Engine",
        daily_routine=build_daily_routine(report, profile, hh),
        indoor_hacks=build_indoor_hacks(report, hh),
        commute_impact=impact,
        indoor_sizing=sizing,
        community_share_text=build_community_share_text(city, report, best_lbl, worst_lbl),
    )
