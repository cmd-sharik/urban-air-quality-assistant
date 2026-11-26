# Urban Air Quality Assistant

**Hack2Skill PromptWars — Challenge 06: Urban Air Quality Assistant**

An intelligent, location-aware air quality and winter-smog protection assistant designed to help urban families, commuters, and civic planners make practical, low-emission daily decisions grounded in live environmental telemetry.

---

## Chosen Vertical & Problem Statement

- **Vertical:** Urban Public Health, Household Air Protection & Sustainable Mobility
- **Challenge Objective:** Help families and communities navigate severe winter smog and urban air pollution through personalized low-emission daily routines, practical indoor air quality hacks, and sustainable alternatives tailored to their location and lifestyle, while clearly explaining the direct impact of their choices.

---

## Approach & Decision-Making Logic

Numerical calculations and safety-critical thresholds are **100% deterministic** in Python (`app/aqi.py` and `app/decision_engine.py`). Google Gemini (`app/ai_advisor.py`) is used strictly to personalize and explain validated facts — never to invent AQI numbers, pollutant readings, or medical diagnoses.

```text
User Input (City + Profile + Optional Household/Commute Context)
   │  POST /api/analyze (Pydantic validation, 16 KB cap, per-IP rate limit)
   ▼
Open-Meteo Geocoding & Air Quality APIs (app/telemetry.py, pooled httpx + TTL caches)
   │  Validates US AQI (missing AQI -> 502, never 0), extracts chronological forecast & 2h windows
   ▼
Deterministic Decision Engine (app/decision_engine.py)
   ├─ Conservative +35 effective AQI buffer for children, older adults, & respiratory sensitivity
   ├─ Time-slotted 4-step daily routine anchored to cleaner vs. peak-smog forecast windows
   ├─ Budget-tiered indoor hacks & HEPA CADR sizing (Area x 2.74 m ceiling x 4-5 ACH)
   ├─ Commute CO2e savings vs. cleaner transit (+/-20% band, India GHG / ICCT / TERI factors)
   └─ Privacy-safe family/community share update (zero personal data)
   ▼
Gemini 2.5 Flash Structured JSON (app/ai_advisor.py) + Safety Guardrails -> Fallback if unavailable
```

### Key Decision Rules
1. **Never fabricate or zero-coerce missing data:** Missing `us_aqi` raises an upstream error (`502`) instead of defaulting to `0` (safe air). Optional secondary pollutants missing from a response render as `Unavailable`.
2. **Chronological forecast & windowing:** Hourly forecasts include only consecutive future hours strictly after the current reading timestamp (local city timezone via `timezone=auto`). Cleaner 2-hour windows are suppressed if outdoor AQI remains > 100 and worse than current conditions.
3. **Safety gates:** Neither the deterministic engine nor Gemini may suggest opening windows when AQI > 100 without a cleaner forecast window, ozone-producing devices, medical diagnoses/prescriptions, or unverified pollutant-reduction percentages.

---

## Implemented Features

- **Modeled Environmental Telemetry (`app/telemetry.py`):** Live US AQI, dominant pollutant relative to WHO 2021 guidelines, pollutant concentrations (`PM2.5`, `PM10`, `NO₂`, `O₃`, plus optional `CO`/`SO₂`), local measurement timestamp, timezone, and explicit model-source provenance.
- **Personalized Daily Routine (`app/decision_engine.py`):** Four time-slotted steps (`Morning`, `Commute`, `Family / Activity`, `Evening / Night`) adapting to sensitivity profile, household risk flags, commute mode, and live forecast windows.
- **Indoor Air Hacks & CADR Sizing:** Budget-tiered guidance (`Free / Zero-Cost`, `Low-Cost (<1500)`, `HEPA Purifier Ready`) plus deterministic room CADR range (`m³/h`).
- **Sustainable Commute Impact:** Compares current commute mode (`Petrol Car`, `Two-Wheeler`, `Bus / Metro`, `Carpool`, `Walk / Cycle`, `Work From Home`) against practical alternatives with daily/annual `kg CO₂e` savings, uncertainty range, and smog-aware mode warnings (favoring enclosed transit over unshielded cycling when `us_aqi > 150`).
- **Accessible Web UI (`static/`):** Semantic landmarks, skip link, keyboard-accessible `<details>` household panel and hourly forecast `<table/>`, `aria-live` status updates, 44 px touch targets, high-contrast toggle, dark-mode support, and `prefers-reduced-motion` support.

---

## Setup & Running Locally

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env   # Optionally set GEMINI_API_KEY
uvicorn app.main:app --reload
```

Open `http://localhost:8000`. Without `GEMINI_API_KEY`, the deterministic decision engine powers all guidance cleanly.

### Quality Checks & Tests

```bash
ruff check .
ruff format --check .
mypy --strict app
node --check static/app.js
python -m pytest
```

### Deployment (Render / Docker)

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Container:** `docker build -t urban-air-quality-assistant . && docker run --rm -p 8000:8000 --env-file .env urban-air-quality-assistant`

---

## API Contract

- `GET /api/health` → `{ "status": "healthy", "version": "3.0.0", "gemini_configured": bool }`
- `POST /api/analyze`
  - Minimal body (backwards compatible): `{ "city": "Jaipur", "profile": "General Citizen" }`
  - Extended body: includes optional `household` (`has_children`, `has_elderly`, `has_respiratory_risk`, `commute_mode`, `commute_distance_km`, `budget_tier`, `owns_purifier`, `room_area_sqft`).
  - Status codes: `200` OK, `400` invalid sanitized city, `404` city not found, `413` payload > 16 KB, `422` schema error, `429` rate limit exceeded, `502` upstream telemetry unavailable.

---

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | Enables Gemini 2.5 Flash explanations | empty (rules engine active) |
| `GEMINI_MODEL` | Gemini model identifier | `gemini-2.5-flash` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | `http://localhost:8000` |

---

## Assumptions & Limitations

- **Modeled data vs. ground stations:** Air quality metrics come from [Open-Meteo / Copernicus CAMS](https://open-meteo.com/en/docs/air-quality-api) atmospheric model estimates on the **US EPA AQI scale** (not Indian NAQI or physical CPCB monitoring stations) and are labeled as such throughout the UI.
- **Tailpipe CO₂e estimates:** Commute savings model tailpipe `CO₂e` only using illustrative urban India fleet factors (`±20%` uncertainty band) and do not claim lifecycle emissions or clinical health-risk percentages.
- **Caching & rate limiting:** Geocoding (24 h) and AQI (15 min) TTL caches and per-IP `slowapi` rate limits (`30/min`) are in-memory per worker process.
- **Not medical advice:** Recommendations are informational public-health guidance only.
