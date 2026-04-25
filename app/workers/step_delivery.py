"""Shared helpers for post-send automation step follow-ups (on_deliver_actions)."""
import logging
from typing import Any, Dict, Optional

from app.workers.actions import execute_on_deliver_action

logger = logging.getLogger(__name__)


def run_step_on_deliver_actions(
    account_id: str,
    contact_ig_id: str,
    step: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Run all on_deliver_actions for a step (same code path for webhook and worker).
    """
    try:
        actions = step.get("on_deliver_actions") or []
        for action in actions:
            logger.debug("Executing on-deliver action: %s", action.get("type"))
            execute_on_deliver_action(
                action, account_id, contact_ig_id, context
            )
    except Exception as e:
        logger.error("Error running on_deliver_actions: %s", e, exc_info=True)
