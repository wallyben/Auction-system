# Continuous scanning

Worker process (`ARIE_PROCESS=worker`, `scripts/start-worker.sh`) owns APScheduler
and the durable pipeline consumer. The web process (`ARIE_PROCESS=web`) is HTTP only.

- Scheduler: `BackgroundScheduler` inside `app.jobs.worker.run_forever`
- Job ids: `scan-live-sources`, `sold-evidence-refresh`, `revalue-after-evidence`,
  `revalue-all-active`, `ebay-deletion-retry`, `daily-self-audit`, `owner-sold-ingest`
- Scheduled functions **enqueue** `pipeline_jobs`. They do not execute scan/revalue/
  sold-refresh/deletion-retry/audit/ingest themselves.
- Scan interval `max(FAST_MARKETPLACE_MINUTES, 5)` plus jitter 30s
- `max_instances=1`, `coalesce=True` per job
- Global `pipeline_jobs` lease so scan / sold-refresh / revalue / scheduler jobs
  cannot overlap
- HTTP `/ops/*` and dashboard triggers enqueue (202) instead of blocking the request
- Web FastAPI lifespan does **not** start the scheduler
- Skipped under pytest unless `ARIE_ALLOW_SCHEDULER=1` and `ARIE_PROCESS=worker`
- Each source search is try/except; errors append to `scan_jobs.details`

Dedup: unique `(source_id, external_id)` on listings and raw_listings.

Retry: httpx + tenacity on timeout/transport/429 with exponential jitter.
