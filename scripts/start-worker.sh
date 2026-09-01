#!/bin/sh
# Dedicated pipeline worker. Never run inside the web process.
# Owns: process heartbeat, APScheduler (enqueue-only), durable job consumer.
set -eu
export ARIE_PROCESS="${ARIE_PROCESS:-worker}"
if [ -n "${DATABASE_URL:-}" ]; then
  i=0
  while [ "$i" -lt 8 ]; do
    if python -m alembic upgrade head; then
      break
    fi
    i=$((i + 1))
    echo "arie-worker: alembic upgrade failed (attempt ${i}/8); retrying" >&2
    sleep 3
  done
fi
exec python -m app.jobs.worker
