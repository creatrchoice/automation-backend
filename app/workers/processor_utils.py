"""Shared helpers for webhook worker processors."""
from typing import Any, Dict, Iterable, Optional
import re

from app.core.config import dm_settings
from app.db.redis import redis_client
from app.db.repositories.account_repository import resolve_account_id_by_ig_user_id


def canonical_trigger_type(raw: Any) -> str:
    """Map trigger type variants to canonical values."""
    if raw is None:
        return ""
    t = str(raw).strip().lower()
    if t in ("comment", "comments"):
        return "comment"
    if t in ("message", "message_received", "dm", "dm_keyword", "messages"):
        return "message"
    return t


def normalize_keyword_rule(keyword: Any) -> Dict[str, Any]:
    """Normalize keyword entries stored as plain strings or objects."""
    if isinstance(keyword, dict):
        return keyword
    if isinstance(keyword, str):
        return {"value": keyword, "match_type": "contains", "case_sensitive": False}
    return {"value": str(keyword), "match_type": "contains", "case_sensitive": False}


def match_keywords(text: str, keywords: Iterable[Any]) -> bool:
    """Evaluate text against exact/contains/regex keyword rules."""
    keywords = list(keywords or [])
    if not keywords:
        return True

    for kw in keywords:
        rule = normalize_keyword_rule(kw)
        match_type = str(rule.get("match_type", "contains")).lower()
        value = str(rule.get("value", ""))
        case_sensitive = bool(rule.get("case_sensitive", False))
        compare_text = text if case_sensitive else text.lower()
        compare_value = value if case_sensitive else value.lower()

        try:
            if match_type == "exact" and compare_text == compare_value:
                return True
            if match_type == "contains" and compare_value in compare_text:
                return True
            if match_type == "regex":
                flags = 0 if case_sensitive else re.IGNORECASE
                if re.search(compare_value, text, flags):
                    return True
        except Exception:
            continue

    return False


def resolve_account_id_with_cache(ig_user_id: str, logger) -> Optional[str]:
    """Resolve internal account id with Redis cache then Cosmos fallback."""
    cache_key = f"account_map:{ig_user_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return cached.decode() if isinstance(cached, bytes) else str(cached)
    except Exception as redis_err:
        logger.warning(
            "Redis unavailable for account_map lookup (ig_user_id=%s): %s",
            ig_user_id,
            redis_err,
        )

    account_id = resolve_account_id_by_ig_user_id(ig_user_id)
    if not account_id:
        return None

    try:
        cache_ttl = dm_settings.ACCOUNT_MAP_CACHE_TTL_HOURS * 3600
        redis_client.setex(cache_key, cache_ttl, account_id)
    except Exception as redis_err:
        logger.warning(
            "Redis unavailable for account_map cache write (ig_user_id=%s): %s",
            ig_user_id,
            redis_err,
        )
    return account_id
