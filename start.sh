#!/bin/bash
set -e
cd /home/mayank/code/automation-backend
export PORT=${PORT:-8000}

echo "Starting Instagram DM Automation Platform..."

# Celery worker (background tasks)
celery -A app.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    -Q default,webhooks,dm_sending,follow_ups,analytics \
    --pidfile=/tmp/celery.pid &

# Celery Beat (scheduled tasks)
celery -A app.tasks.celery_app beat \
    --loglevel=info \
    --schedule=/tmp/celerybeat-schedule \
    --pidfile=/tmp/celerybeat.pid &

# Gunicorn with uvicorn workers (API server)
exec gunicorn main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -