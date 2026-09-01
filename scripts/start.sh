#!/bin/sh
# Production web entrypoint: migrate (best-effort) then serve HTTP only.
# APScheduler and pipeline execution live in scripts/start-worker.sh.
# Alembic is idempotent. Failure does not take down the eBay GET challenge.
set -eu
export ARIE_PROCESS="${ARIE_PROCESS:-web}"
PORT="${PORT:-8000}"
if [ -n "${DATABASE_URL:-}" ]; then
  i=0
  while [ "$i" -lt 8 ]; do
    if python -m alembic upgrade head; then
      break
    fi
    i=$((i + 1))
    echo "arie: alembic upgrade failed (attempt ${i}/8); retrying" >&2
    sleep 3
  done
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
