"""Shared helpers for post-send automation step follow-ups (on_deliver_actions)."""
import json
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
        logger.info(
            "Running on_deliver_actions account_id=%s contact_id=%s step_id=%s action_count=%s comment_id=%s",
            account_id,
            contact_ig_id,
            step.get("id"),
            len(actions),
            (context or {}).get("comment_id"),
        )
        logger.info(
            "RAW on_deliver context step_id=%s context=%s",
            step.get("id"),
            json.dumps(context or {}, ensure_ascii=True, default=str),
        )
        for action in actions:
            logger.info(
                "Executing on-deliver action type=%s account_id=%s contact_id=%s step_id=%s",
                action.get("type"),
                account_id,
                contact_ig_id,
                step.get("id"),
            )
            logger.info(
                "RAW on_deliver action step_id=%s action=%s",
                step.get("id"),
                json.dumps(action, ensure_ascii=True, default=str),
            )
            execute_on_deliver_action(
                action, account_id, contact_ig_id, context
            )
    except Exception as e:
        logger.error("Error running on_deliver_actions: %s", e, exc_info=True)
