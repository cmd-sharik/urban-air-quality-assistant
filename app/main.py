"""
FastAPI application entrypoint for the Urban Air Quality Assistant.
"""

from pathlib import Path
from typing import Dict
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.models import AdvisoryRequest, AnalysisResponse
from app.services import (
    fetch_air_quality_report,
    fetch_city_location,
    generate_genai_advisory,
    sanitize_city_input,
)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.app_title,
    description="AI-powered hyperlocal air quality monitor and public health/commute advisor.",
    version=settings.app_version,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    """Attach hardened security headers to all outgoing HTTP responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:;"
    )
    return response


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the WCAG 2.1 AA compliant single-page web interface."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", tags=["System"])
async def health_check() -> Dict[str, str]:
    """Return service liveness and version metadata."""
    return {"status": "healthy", "version": settings.app_version}


@app.post("/api/analyze", response_model=AnalysisResponse, tags=["Air Quality"])
@limiter.limit("30/minute")
async def analyze_urban_air(request: Request, payload: AdvisoryRequest) -> AnalysisResponse:
    """Fetch live air quality telemetry and generate personalized Gemini AI guidance."""
    clean_city = sanitize_city_input(payload.city)
    if len(clean_city) < 2:
        raise HTTPException(status_code=400, detail="Please provide a valid city name.")

    async with httpx.AsyncClient() as client:
        try:
            location = await fetch_city_location(clean_city, client)
            if not location:
                raise HTTPException(status_code=404, detail=f"City '{clean_city}' was not found.")

            report = await fetch_air_quality_report(
                location.latitude, location.longitude, client
            )
            advisory = await generate_genai_advisory(
                location.name, payload.profile, report, client
            )
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail="Upstream air quality telemetry service is temporarily unavailable.",
            ) from exc

    return AnalysisResponse(
        location=location,
        profile=payload.profile,
        air_quality=report,
        advisory=advisory,
    )
