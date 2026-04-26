"""Centralized logging for webhook processing failures (worker path, not HTTP)."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def log_webhook_processing_failure(
    event: Dict[str, Any],
    *,
    event_type: Any,
    webhook_id: str,
    exc: BaseException,
) -> None:
    """
    Log one structured record for a failed process_webhook_event.

    The caller is responsible for persisting (e.g. _store_failed_webhook_event) and re-raising.
    """
    account_id = event.get("ig_account_id")
    logger.exception(
        "Webhook processing failed webhook_id=%s event_type=%s ig_account_id=%s",
        webhook_id,
        event_type,
        account_id,
        exc_info=exc,
    )
