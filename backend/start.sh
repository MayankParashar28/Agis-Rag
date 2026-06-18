#!/bin/bash
# Start the Celery background worker
celery -A app.worker.celery_app worker --loglevel=info &

# Start the Uvicorn server
uvicorn app.main:app --host 0.0.0.0 --port 8000
