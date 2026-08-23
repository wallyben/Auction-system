# Security review

- Secrets live in `.env`, gitignored. Rotate any key that ever landed in git (none found in tracked files).
- SQLAlchemy bound parameters; no raw string SQL in adapters.
- Dashboard token `ARIE_DASHBOARD_TOKEN` is optional; empty means local-open. Set it before exposing the port.
- SSRF: listing URLs are stored, not fetched as owner-controlled server-side browsers except adapter allow-listed hosts.
- No credential logging in structlog processors for token fields.
- Reverb 403 is treated as BLOCKED_TECHNICAL, not bypassed.
- Dependency set is small (FastAPI, SQLAlchemy, httpx, APScheduler, feedparser). Run `pip audit` in CI when you add a pipeline.

Residual risk: unauthenticated local dashboard; XSS if a source title contains HTML — templates should keep auto-escape (Jinja2 default on).
