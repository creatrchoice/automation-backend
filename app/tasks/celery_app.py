"""Celery application initialization with Azure Service Bus broker."""
import logging
from celery import Celery
from app.core.config import dm_settings
from app.core.logging_config import setup_logging

logger = logging.getLogger(__name__)

# Initialize logging
setup_logging()

# Create Celery app
# NOTE: Celery fallback for webhooks uses Redis as broker. Azure Service Bus is
# handled directly in app/api/webhooks.py and is not a Celery transport URL.
celery_app = Celery(
    main="dm_automation",
    broker="redis{ssl}://{user}:{pwd}@{host}:{port}/0".format(
        ssl="s" if dm_settings.REDIS_SSL else "",
        user=dm_settings.REDIS_USERNAME or "",
        pwd=dm_settings.REDIS_PASSWORD or "",
        host=dm_settings.REDIS_HOST or "localhost",
        port=dm_settings.REDIS_PORT or 6379,
    ),
    backend="redis{ssl}://{user}:{pwd}@{host}:{port}/1".format(
        ssl="s" if dm_settings.REDIS_SSL else "",
        user=dm_settings.REDIS_USERNAME or "",
        pwd=dm_settings.REDIS_PASSWORD or "",
        host=dm_settings.REDIS_HOST or "localhost",
        port=dm_settings.REDIS_PORT or 6379,
    ),
)

# Load configuration
celery_app.config_from_object("app.tasks.celery_config:CeleryConfig")

# Auto-discover tasks from all modules
celery_app.autodiscover_tasks(
    [
        "app.tasks.token_refresh",
        "app.tasks.scheduled_tasks",
        "app.tasks.analytics_aggregator",
    ]
)


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery."""
    logger.info(f"Debug task called: {self.request.id}")
    print(f"Request: {self.request!r}")


@celery_app.task(bind=True, max_retries=3)
def trigger_automation(self, account_id: str, contact_id: str, automation_id: str):
    """
    Trigger an automation for a contact.

    Args:
        self: Celery task instance
        account_id: Account ID
        contact_id: Contact ID
        automation_id: Automation ID
    """
    try:
        logger.info(
            f"Triggering automation {automation_id} "
            f"for account {account_id}, contact {contact_id}"
        )

        from app.services.automation_engine import automation_engine

        automation_engine.execute_automation(
            automation_id, account_id, contact_id
        )

    except Exception as e:
        logger.error(f"Error triggering automation: {str(e)}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)


if __name__ == "__main__":
    celery_app.start()
