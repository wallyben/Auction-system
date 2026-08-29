# Continuous scanning

Worker: APScheduler `AsyncIOScheduler` inside the FastAPI lifespan.

- Job ids: `scan-live-sources`, `sold-evidence-refresh`, `revalue-after-evidence`, `revalue-all-active`
- Scan interval `max(FAST_MARKETPLACE_MINUTES, 5)` plus jitter 30s
- `max_instances=1`, `coalesce=True` per job
- Global `pipeline_jobs` lease so scan / sold-refresh / revalue cannot overlap on the single worker
- HTTP `/ops/*` and dashboard triggers enqueue (202) instead of blocking the request
- Skipped under pytest
- Each source search is try/except; errors append to `scan_jobs.details`

Dedup: unique `(source_id, external_id)` on listings and raw_listings.

Retry: httpx + tenacity on timeout/transport/429 with exponential jitter.

This is not a distributed fleet. One API process is the worker. For multi-instance deploy, run scans in a single worker process only.
