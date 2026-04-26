"""Evaluate automation `conditions` (cooldown, field rules) and legacy `trigger_conditions`."""
import logging
import re
from typing import Any, Dict

from app.db.redis import redis_client

logger = logging.getLogger(__name__)

COOLDOWN_KEY_PREFIX = "automation_cooldown:"


def _cooldown_key(automation_id: str, user_ig_id: str) -> str:
    return f"{COOLDOWN_KEY_PREFIX}{automation_id}:{user_ig_id}"


def is_within_cooldown(automation: Dict[str, Any], from_id: str) -> bool:
    """True if a cooldown Redis key exists for this automation + user."""
    if not from_id or not automation or not automation.get("id"):
        return False
    try:
        return bool(redis_client.get(_cooldown_key(automation["id"], str(from_id))))
    except Exception as exc:  # noqa: BLE001 — fail open: do not block sends if Redis is down
        logger.warning(
            "Redis cooldown read failed, allowing send: automation_id=%s %s",
            automation.get("id"),
            exc,
        )
        return False


def set_cooldown_after_send(
    automation: Dict[str, Any], from_id: str, hours: float
) -> None:
    if not from_id or not automation or hours <= 0 or not automation.get("id"):
        return
    ttl = max(1, int(hours * 3600))
    redis_client.setex(_cooldown_key(automation["id"], str(from_id)), ttl, "1")


def _field_condition_matches(
    context: Dict[str, Any], field: str, match_type: str, expected: Any
) -> bool:
    context_value = context.get(field, "")
    context_str = str(context_value).lower()
    expected_str = str(expected).lower()

    if match_type == "equals":
        return context_str == expected_str
    if match_type == "contains":
        return expected_str in context_str
    if match_type == "starts_with":
        return context_str.startswith(expected_str)
    if match_type == "ends_with":
        return context_str.endswith(expected_str)
    if match_type == "regex":
        return bool(re.search(expected_str, context_str))
    return False


def passes_comment_automation_conditions(
    automation: Dict[str, Any], context: Dict[str, Any]
) -> bool:
    for c in automation.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        if (c.get("type") or "").lower() == "cooldown":
            if float(c.get("hours") or 0) > 0 and is_within_cooldown(
                automation, str(context.get("from_id", ""))
            ):
                return False
        elif c.get("field") and not _field_condition_matches(
            context,
            str(c.get("field", "")),
            str(c.get("match_type", "equals")),
            c.get("value", ""),
        ):
            return False
    for c in automation.get("trigger_conditions") or []:
        if not isinstance(c, dict):
            continue
        if not _field_condition_matches(
            context,
            str(c.get("field", "")),
            str(c.get("match_type", "equals")),
            c.get("value", ""),
        ):
            return False
    return True


def apply_cooldown_from_automation(
    automation: Dict[str, Any], from_id: str
) -> None:
    """Set Redis TTL from the first `conditions` entry with ``type: cooldown``."""
    for c in automation.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        if (c.get("type") or "").lower() == "cooldown":
            h = float(c.get("hours") or 0)
            if h > 0:
                set_cooldown_after_send(automation, from_id, h)
            return
