# Urban Air Quality Assistant

AI-powered hyperlocal air quality monitor and public health advisor built for **Challenge 6: Urban Air Quality Assistant**.

## Key Features & Evaluation Alignment
- **Problem Statement Alignment:** Real-time US AQI and pollutant tracking (PM2.5, PM10, NO₂, O₃) paired with role-based health, commute, and civic mitigation guidance.
- **GenAI Service (`Google Gemini 2.5 Flash`):** Synthesizes raw atmospheric telemetry into personalized advisories with a resilient fallback engine.
- **Efficiency:** Asynchronous `httpx` client + 15-minute TTL caching (`cachetools`) for ultra-low latency.
- **Security:** Pydantic input validation, XSS/prompt sanitization, IP rate limiting (`slowapi`), and HTTP security headers (`X-Frame-Options`, `X-Content-Type-Options`).
- **Accessibility (WCAG 2.1 AA):** Semantic landmarks, skip-to-content navigation, ARIA live regions, and high-contrast visual indicators.
- **Testing:** Automated `pytest` unit & integration suite in `tests/test_main.py`.
