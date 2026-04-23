"""Celery configuration and beat schedule."""
from celery.schedules import crontab
from app.core.config import dm_settings


class CeleryConfig:
    """Celery configuration."""

    # Broker settings - Redis broker for Celery task queueing
    _redis_scheme = "rediss" if dm_settings.REDIS_SSL else "redis"
    _redis_url = f"{_redis_scheme}://{dm_settings.REDIS_USERNAME or ''}:{dm_settings.REDIS_PASSWORD or ''}@{dm_settings.REDIS_HOST or 'localhost'}:{dm_settings.REDIS_PORT or 6379}"

    broker_url = f"{_redis_url}/0"
    broker_transport_options = {
        "visibility_timeout": 3600,  # 1 hour
        "max_retries": 3,
    }

    # Result backend (Redis)
    result_backend = f"{_redis_url}/1"
    result_expires = 3600  # Results expire after 1 hour

    # Redis SSL options (required by kombu when using rediss://)
    if dm_settings.REDIS_SSL:
        import ssl as _ssl
        broker_use_ssl = {"ssl_cert_reqs": _ssl.CERT_NONE}
        redis_backend_use_ssl = {"ssl_cert_reqs": _ssl.CERT_NONE}

    # Task settings
    task_serializer = "json"
    accept_content = ["json"]
    result_serializer = "json"
    timezone = "UTC"
    enable_utc = True

    # Task execution settings
    task_track_started = True
    task_time_limit = 30 * 60  # 30 minutes hard limit
    task_soft_time_limit = 25 * 60  # 25 minutes soft limit
    task_acks_late = True  # Acknowledge after task completion
    worker_prefetch_multiplier = 4  # Prefetch 4 tasks at a time

    # Retry settings
    task_autoretry_for = (Exception,)
    task_max_retries = 3
    task_default_retry_delay = 60  # Retry after 60 seconds

    # Beat schedule for periodic tasks
    beat_schedule = {
        "token-refresh-daily": {
            "task": "app.tasks.token_refresh.refresh_expired_tokens",
            "schedule": crontab(hour=3, minute=0),  # 3 AM daily
            "options": {"expires": 3600},
        },
        "poll-scheduled-tasks": {
            "task": "app.tasks.scheduled_tasks.poll_and_execute_scheduled_tasks",
            "schedule": 30.0,  # Every 30 seconds
            "options": {"expires": 25},
        },
        "analytics-rollup-daily": {
            "task": "app.tasks.analytics_aggregator.aggregate_message_logs",
            "schedule": crontab(hour=1, minute=0),  # 1 AM daily
            "options": {"expires": 3600},
        },
    }

    # Worker settings
    worker_max_tasks_per_child = 1000
    worker_disable_rate_limits = False

    # Task routing (if needed)
    task_routes = {}

    # Error handling
    task_reject_on_worker_lost = True
    task_publish_retry = True
    task_publish_retry_policy = {
        "max_retries": 3,
        "interval_start": 0.1,
        "interval_step": 0.2,
        "interval_max": 0.2,
    }
