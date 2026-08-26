# Continuous scanning

Worker: APScheduler `AsyncIOScheduler` inside the FastAPI lifespan.

- Job id `scan-live-sources`
- Interval `max(FAST_MARKETPLACE_MINUTES, 5)` plus jitter 30s
- `max_instances=1`, `coalesce=True`
- In-process `_running` guard
- Skipped under pytest
- Each source search is try/except; errors append to `scan_jobs.details`

Dedup: unique `(source_id, external_id)` on listings and raw_listings.

Retry: httpx + tenacity on timeout/transport/429 with exponential jitter.

This is not a distributed fleet. One API process is the worker. For multi-instance deploy, run scans in a single worker process only.
