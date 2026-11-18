"""
Urban Air Quality Assistant - FastAPI Backend & GenAI Environmental Engine.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Literal, Optional
import httpx
from cachetools import TTLCache
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Urban Air Quality Assistant", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

GEO_CACHE: TTLCache = TTLCache(maxsize=256, ttl=86400)
AQI_CACHE: TTLCache = TTLCache(maxsize=256, ttl=900)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


class AdvisoryRequest(BaseModel):
    city: str = Field(..., min_length=2, max_length=80)
    profile: Literal[
        "General Citizen",
        "Child / Elderly",
        "Asthma / Respiratory Sensitivity",
        "Outdoor Athlete",
        "Urban Planner",
    ] = "General Citizen"


def sanitize_text(text: str) -> str:
    return re.sub(r"[<>\"';`]", "", text.strip())[:80]


def classify_aqi(aqi: int) -> Dict[str, str]:
    if aqi <= 50:
        return {"category": "Good", "risk": "Low", "badge": "GOOD"}
    if aqi <= 100:
        return {"category": "Moderate", "risk": "Moderate", "badge": "MODERATE"}
    if aqi <= 150:
        return {"category": "Unhealthy for Sensitive Groups", "risk": "Elevated", "badge": "SENSITIVE"}
    if aqi <= 200:
        return {"category": "Unhealthy", "risk": "High", "badge": "UNHEALTHY"}
    return {"category": "Hazardous", "risk": "Severe", "badge": "HAZARDOUS"}


async def get_coordinates(city: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    key = city.lower()
    if key in GEO_CACHE:
        return GEO_CACHE[key]
    res = await client.get(GEOCODE_URL, params={"name": city, "count": 1, "format": "json"}, timeout=8.0)
    res.raise_for_status()
    results = res.json().get("results")
    if not results:
        return None
    loc = {
        "name": results[0].get("name", city),
        "country": results[0].get("country", ""),
        "latitude": results[0]["latitude"],
        "longitude": results[0]["longitude"],
    }
    GEO_CACHE[key] = loc
    return loc


async def get_aqi_data(lat: float, lon: float, client: httpx.AsyncClient) -> Dict[str, Any]:
    key = f"{round(lat, 2)}:{round(lon, 2)}"
    if key in AQI_CACHE:
        return AQI_CACHE[key]
    res = await client.get(
        AIR_QUALITY_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm10,pm2_5,nitrogen_dioxide,ozone",
        },
        timeout=8.0,
    )
    res.raise_for_status()
    curr = res.json().get("current", {})
    aqi_val = int(curr.get("us_aqi") or 0)
    meta = classify_aqi(aqi_val)
    data = {
        "us_aqi": aqi_val,
        "category": meta["category"],
        "risk_level": meta["risk"],
        "badge": meta["badge"],
        "pollutants": {
            "pm2_5": round(float(curr.get("pm2_5") or 0), 1),
            "pm10": round(float(curr.get("pm10") or 0), 1),
            "no2": round(float(curr.get("nitrogen_dioxide") or 0), 1),
            "o3": round(float(curr.get("ozone") or 0), 1),
        },
    }
    AQI_CACHE[key] = data
    return data


async def get_ai_advisory(city: str, profile: str, aqi_data: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    p = aqi_data["pollutants"]
    aqi = aqi_data["us_aqi"]

    if api_key:
        prompt = (
            f"Urban Air Quality Assistant for {city} (Profile: {profile}). "
            f"US AQI: {aqi}, PM2.5: {p['pm2_5']}, PM10: {p['pm10']}, NO2: {p['no2']}, O3: {p['o3']}. "
            f"Reply in 3 short lines labeled exactly:\n"
            f"HEALTH: <personalized health & outdoor advice>\n"
            f"COMMUTE: <safe travel & mask/ventilation tip>\n"
            f"URBAN: <municipal/civic mitigation action>"
        )
        try:
            res = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}},
                timeout=10.0,
            )
            res.raise_for_status()
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            out = {"health": "", "commute": "", "urban": "", "source": "Google Gemini 2.5 Flash"}
            for line in text.splitlines():
                clean = line.replace("*", "").strip()
                if clean.upper().startswith("HEALTH:"):
                    out["health"] = clean.split(":", 1)[1].strip()
                elif clean.upper().startswith("COMMUTE:"):
                    out["commute"] = clean.split(":", 1)[1].strip()
                elif clean.upper().startswith("URBAN:"):
                    out["urban"] = clean.split(":", 1)[1].strip()
            if out["health"] and out["commute"]:
                out["urban"] = out["urban"] or "Deploy anti-smog misting and restrict heavy diesel entry in peak hours."
                return out
        except Exception:
            pass

    return {
        "health": f"AQI in {city} is {aqi} ({aqi_data['category']}). {profile} individuals should adjust outdoor intensity accordingly.",
        "commute": "Use N95 mask near heavy traffic junctions and keep vehicle cabin air on recirculation mode." if aqi > 100 else "Walking and cycling are safe along green corridors.",
        "urban": "Prioritize dust suppression on arterial roads and optimize traffic signal flow to curb NO2 buildup.",
        "source": "Gemini Environmental Fallback Engine",
    }


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.post("/api/analyze")
@limiter.limit("30/minute")
async def analyze(request: Request, payload: AdvisoryRequest):
    city = sanitize_text(payload.city)
    async with httpx.AsyncClient() as client:
        loc = await get_coordinates(city, client)
        if not loc:
            raise HTTPException(status_code=404, detail=f"City '{city}' not found.")
        aqi_data = await get_aqi_data(loc["latitude"], loc["longitude"], client)
        advisory = await get_ai_advisory(loc["name"], payload.profile, aqi_data, client)
    return JSONResponse({"location": loc, "profile": payload.profile, "air_quality": aqi_data, "advisory": advisory})
