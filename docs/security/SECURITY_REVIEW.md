# Security review

- `.env` is gitignored. No tracked secrets found in source.
- Dashboard token (`ARIE_DASHBOARD_TOKEN`) remains optional; do not expose the app to the public internet without it and a reverse proxy.
- URL valuation allow-lists hosts and rejects localhost / RFC1918 (SSRF).
- CSV import rejects NUL/binary and requires headers. Size is bounded by typical multipart limits.
- SQLAlchemy bound parameters; no raw string SQL in application paths except Alembic DDL.
- eBay/Reverb tokens never logged on purpose.
- Dependency CVEs were not exhaustively scanned in this environment; run `pip-audit` on the owner host before production exposure.
- CSRF: cookie-less local dashboard POSTs. Add auth + CSRF if published.
- XSS: templates escape by default; do not mark listing titles `|safe`.
