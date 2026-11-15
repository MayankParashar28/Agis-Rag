#!/bin/bash
set -e

# Indexing runs inside the API by default (INDEXING_MODE=inprocess), so no
# Celery worker is started and nothing polls Redis while the app is idle.
# Set INDEXING_MODE=celery to run a separate worker instead.
export INDEXING_MODE="${INDEXING_MODE:-inprocess}"

if [ "$INDEXING_MODE" = "celery" ]; then
  # --without-gossip/mingle/heartbeat: skip worker-to-worker chatter that
  # this app does not use but that costs Redis commands around the clock.
  celery -A app.worker.celery_app worker --loglevel=info \
    --without-gossip --without-mingle --without-heartbeat &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
