# Owner runbook

1. `cp .env.example .env` and set `DATABASE_URL`.
2. `make install && make migrate && make dev`
3. Open http://127.0.0.1:8000
4. Click **Scan all sources now** or `make scan`
5. Open a row: max buy, expected Irish resale, costs, comps, risks, why
6. Watch / ignore / record purchase from the API or dashboard actions
7. Record actual sale later so prediction error can be computed

## Continuous scanning

APScheduler starts with the API if `SCAN_ENABLED=true`. Cadence: `FAST_MARKETPLACE_MINUTES` (default 15) with jitter. Overlapping scans are skipped. Source 403/404 cannot kill the job.

Disable: `SCAN_ENABLED=false`.

## Credentials

- eBay: `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`
- Optional Reverb token: `REVERB_TOKEN`
- Alerts: Discord webhook, Telegram, SMTP

## CSV

POST `/import/csv` with columns: source, external_id, url, title, price, currency, country, condition, brand, model.
