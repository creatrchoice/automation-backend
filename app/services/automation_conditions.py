"""Evaluate automation `conditions` (cooldown, field rules) and legacy `trigger_conditions`."""
import logging
import re
from typing import Any, Dict, List

from app.db.redis import redis_client

logger = logging.getLogger(__name__)

COOLDOWN_KEY_PREFIX = "automation_cooldown:"


def _cooldown_key(automation_id: str, user_ig_id: str) -> str:
    return f"{COOLDOWN_KEY_PREFIX}{automation_id}:{user_ig_id}"


def is_within_cooldown(automation: Dict[str, Any], from_id: str) -> bool:
    """
    Return True if this user is still within a cooldown window for this automation
    (Redis key exists). On Redis error, fail open (treat as not in cooldown).
    """
    if not from_id or not automation:
        return False
    aid = automation.get("id")
    if not aid:
        return False
    try:
        return bool(redis_client.get(_cooldown_key(aid, str(from_id))))
    except Exception as e:
        logger.warning(
            "Redis cooldown read failed; allowing run (fail-open) automation_id=%s error=%s",
            aid,
            e,
        )
        return False


def set_cooldown_after_send(
    automation: Dict[str, Any], from_id: str, hours: float
) -> None:
    """Set Redis key with TTL = hours (fractional) after a successful send."""
    if not from_id or not automation or hours <= 0:
        return
    aid = automation.get("id")
    if not aid:
        return
    ttl = max(1, int(hours * 3600))
    key = _cooldown_key(aid, str(from_id))
    try:
        redis_client.setex(key, ttl, "1")
    except Exception as e:
        logger.warning(
            "Redis cooldown set failed automation_id=%s from_id=%s error=%s",
            aid,
            from_id,
            e,
        )


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


def _evaluate_top_level_conditions(
    conditions: List[Dict[str, Any]], automation: Dict[str, Any], context: Dict[str, Any]
) -> bool:
    """`conditions` array: cooldown, or field/match (ConditionSchema style)."""
    for c in conditions or []:
        if not isinstance(c, dict):
            continue
        ctype = (c.get("type") or "").lower()
        if ctype == "cooldown":
            hours = float(c.get("hours") or 0)
            if hours > 0 and is_within_cooldown(automation, str(context.get("from_id", ""))):
                return False
            continue
        if c.get("field"):
            if not _field_condition_matches(
                context,
                str(c.get("field", "")),
                str(c.get("match_type", "equals")),
                c.get("value", ""),
            ):
                return False
    return True


def _evaluate_legacy_trigger_conditions(
    conditions: List[Dict[str, Any]], context: Dict[str, Any]
) -> bool:
    """Legacy `trigger_conditions` with {field, match_type, value}."""
    for condition in conditions or []:
        if not isinstance(condition, dict):
            continue
        field = str(condition.get("field", ""))
        match_type = str(condition.get("match_type", "equals"))
        value = condition.get("value", "")
        if not _field_condition_matches(context, field, match_type, value):
            return False
    return True


def passes_comment_automation_conditions(
    automation: Dict[str, Any], context: Dict[str, Any]
) -> bool:
    """
    All configured conditions pass for this comment event.

    - `automation.conditions` (list): `type: cooldown`, or field/match rules.
    - `automation.trigger_conditions` (legacy): same field/match list as before.
    """
    if not _evaluate_top_level_conditions(
        list(automation.get("conditions") or []), automation, context
    ):
        return False
    return _evaluate_legacy_trigger_conditions(
        list(automation.get("trigger_conditions") or []), context
    )


def apply_cooldown_from_automation(
    automation: Dict[str, Any], from_id: str
) -> None:
    """
    After a successful run, set cooldown TTL from the first `conditions` cooldown entry.
    """
    for c in automation.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        if (c.get("type") or "").lower() == "cooldown":
            h = float(c.get("hours") or 0)
            if h > 0:
                set_cooldown_after_send(automation, from_id, h)
            return
