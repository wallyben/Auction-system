# Owner runbook

1. `cp .env.example .env` and set `DATABASE_URL`.
2. `make install && make migrate && make dev`
3. Open http://127.0.0.1:8000
4. Click **Scan all sources now** or `make scan`
5. Open a row: max buy, expected Irish resale, costs, comps, risks, why
6. Watch / ignore / record purchase from the API or dashboard actions
7. Record actual sale later so prediction error can be computed

## Continuous scanning

APScheduler starts in the **worker** process if `SCAN_ENABLED=true`. The web API does not own the scheduler. Cadence: `FAST_MARKETPLACE_MINUTES` (default 15) with jitter. Overlapping pipeline jobs are skipped via the durable lease. Source 403/404 cannot kill the job.

Disable: `SCAN_ENABLED=false`.

## Render production (web + worker)

The web process must not run scan/revalue/sold jobs. Add a Background Worker on the same service group / `DATABASE_URL`:

- Web start command: `sh scripts/start.sh` (alembic + uvicorn)
- Worker start command: `sh scripts/start-worker.sh` (`python -m app.jobs.worker`)

See `render.yaml`. After deploy, confirm `GET /health/jobs` shows `worker_connected: true` before triggering revalue.

## Credentials

- eBay: `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`
- Optional Reverb token: `REVERB_TOKEN`
- Alerts: Discord webhook, Telegram, SMTP

## CSV

POST `/import/csv` with columns: source, external_id, url, title, price, currency, country, condition, brand, model.
