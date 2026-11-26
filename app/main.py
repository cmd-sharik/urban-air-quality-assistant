"""FastAPI application entrypoint for the Urban Air Quality Assistant."""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.ai_advisor import generate_genai_advisory
from app.aqi import sanitize_city_input
from app.config import settings
from app.models import AdvisoryRequest, AnalysisResponse
from app.telemetry import UpstreamServiceError, fetch_air_quality_report, fetch_city_location

logger = logging.getLogger("app.access")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage a pooled async HTTP client across application startup and shutdown."""
    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(transport=transport) as client:
        application.state.http_client = client
        yield


app = FastAPI(
    title=settings.app_title,
    description=(
        "Intelligent urban air quality assistant providing modeled telemetry, "
        "personalized routines, indoor air sizing, commute impact math, and Gemini guidance."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)
app.state.limiter = limiter


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured JSON 429 response with Retry-After header."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment and try again."},
        headers={"Retry-After": "60"},
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _apply_response_headers(request: Request, response: Response, request_id: str) -> None:
    """Attach security, CSP, and cache-control headers consistently."""
    response.headers["X-Request-ID"] = request_id
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"


def _payload_too_large_response(request: Request, request_id: str) -> JSONResponse:
    """Build a consistent 413 response with hardened security headers."""
    resp = JSONResponse(
        status_code=413,
        content={"detail": "Request payload exceeds the 16 KB limit."},
    )
    _apply_response_headers(request, resp, request_id)
    return resp


@app.middleware("http")
async def security_and_size_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Enforce request size limits, attach security headers, and log request latency."""
    incoming_id = request.headers.get("X-Request-ID", "")
    request_id = incoming_id if REQUEST_ID_PATTERN.match(incoming_id) else uuid.uuid4().hex
    started = time.perf_counter()

    content_len = request.headers.get("Content-Length")
    if content_len and content_len.isdigit() and int(content_len) > settings.max_request_bytes:
        return _payload_too_large_response(request, request_id)

    if request.method == "POST" and len(await request.body()) > settings.max_request_bytes:
        return _payload_too_large_response(request, request_id)

    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    _apply_response_headers(request, response, request_id)
    return response


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the single-page web interface."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", tags=["System"])
async def health_check() -> dict[str, object]:
    """Return service liveness, version, and non-secret provider configuration flags."""
    gemini_ready = bool(
        settings.gemini_api_key and settings.gemini_api_key != "your_google_gemini_api_key_here"
    )
    return {
        "status": "healthy",
        "version": settings.app_version,
        "gemini_configured": gemini_ready,
    }


async def _get_http_client(request: Request) -> tuple[httpx.AsyncClient, bool]:
    """Reuse the lifespan pooled HTTP client, or create a scoped fallback for test clients."""
    pooled = getattr(request.app.state, "http_client", None)
    if isinstance(pooled, httpx.AsyncClient):
        return pooled, False
    transport = httpx.AsyncHTTPTransport(retries=2)
    return httpx.AsyncClient(transport=transport), True


async def _build_analysis(
    request: Request, clean_city: str, payload: AdvisoryRequest
) -> AnalysisResponse:
    """Resolve the city, fetch telemetry, and generate personalized guidance."""
    client, should_close = await _get_http_client(request)
    try:
        location = await fetch_city_location(clean_city, client)
        if not location:
            raise HTTPException(status_code=404, detail=f"City '{clean_city}' was not found.")

        report = await fetch_air_quality_report(location.latitude, location.longitude, client)
        advisory = await generate_genai_advisory(
            location.name, payload.profile, report, client, payload.household
        )
    except HTTPException:
        raise
    except (UpstreamServiceError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Upstream air quality telemetry service is temporarily unavailable.",
        ) from exc
    finally:
        if should_close:
            await client.aclose()

    return AnalysisResponse(
        location=location,
        profile=payload.profile,
        air_quality=report,
        advisory=advisory,
    )


@app.post("/api/analyze", response_model=AnalysisResponse, tags=["Air Quality"])
@limiter.limit("30/minute")
async def analyze_urban_air(request: Request, payload: AdvisoryRequest) -> AnalysisResponse:
    """Fetch modeled air quality telemetry and generate personalized protection guidance."""
    clean_city = sanitize_city_input(payload.city)
    if len(clean_city) < 2:
        raise HTTPException(status_code=400, detail="Please provide a valid city name.")
    return await _build_analysis(request, clean_city, payload)
