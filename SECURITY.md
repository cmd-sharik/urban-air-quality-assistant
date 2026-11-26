# Security Policy

- Secrets (`GEMINI_API_KEY`) are read strictly from server-side environment variables, sent via the `x-goog-api-key` header, never committed, and never exposed to client JavaScript or health endpoints.
- User input is strictly validated with Pydantic (`extra="forbid"`), Unicode-sanitized, and capped at 16 KB (`413 Payload Too Large`).
- Untrusted environmental context is separated from Gemini `systemInstruction`, and AI responses undergo deterministic safety and markup/URL validation before rendering.
- Responses include hardened CSP (`object-src 'none'`, `frame-ancestors 'none'`), HSTS, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `COOP`, and `CORP` headers.
- `/api/analyze` enforces per-IP rate limiting (`30/minute`).
- To report a security issue, please open a private security advisory on GitHub.
