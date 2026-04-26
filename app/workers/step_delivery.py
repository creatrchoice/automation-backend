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

        # Backward-compat: older/newer workflow schema may store public reply
        # config directly on the step instead of on_deliver_actions.
        if not actions and step.get("public_reply_enabled"):
            variants = step.get("public_reply_variants") or []
            public_reply_text = ""
            if isinstance(variants, list) and variants:
                public_reply_text = str(variants[0] or "").strip()
            if public_reply_text:
                actions = [
                    {
                        "type": "reply_to_instagram_comment",
                        "message": public_reply_text,
                        "only_if_send_succeeded": True,
                    }
                ]
                logger.info(
                    "Synthesized on_deliver public reply action from step config step_id=%s message=%s",
                    step.get("id"),
                    public_reply_text,
                )

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
