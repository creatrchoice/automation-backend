"""Pure matching helpers for automation trigger evaluation."""
from typing import Any, Dict, List

from app.workers.processor_utils import canonical_trigger_type, match_keywords


def effective_automation_type(automation: Dict[str, Any]) -> str:
    """Derive effective automation type from automation_type or trigger object."""
    explicit = automation.get("automation_type")
    if explicit:
        return str(explicit).lower().replace("-", "_")

    trigger = automation.get("trigger") or {}
    trigger_type = trigger.get("type") or "message_received"
    if isinstance(trigger_type, str):
        trigger_type = trigger_type.lower().replace("-", "_")
    else:
        trigger_type = "message_received"

    if trigger_type in ("keyword", "dm_keyword"):
        return "dm_keyword"
    if trigger_type in ("story_reaction", "story_reply", "story"):
        return "story_reaction"
    if trigger_type == "message_received" and (trigger.get("keywords") or []):
        return "dm_keyword"
    return trigger_type


def _keywords_for_automation(automation: Dict[str, Any]) -> List[str]:
    raw = automation.get("keywords")
    if raw is None:
        raw = (automation.get("trigger") or {}).get("keywords", [])
    output: List[str] = []
    for item in raw or []:
        if isinstance(item, dict):
            value = item.get("value") or item.get("text") or ""
            if value:
                output.append(str(value))
        elif item is not None and str(item).strip():
            output.append(str(item).strip())
    return output


def _trigger_story_ids(automation: Dict[str, Any]) -> List[str]:
    ids = automation.get("trigger_stories")
    if ids is None:
        ids = (automation.get("trigger") or {}).get("trigger_stories", [])
    return [str(story_id) for story_id in (ids or []) if story_id is not None]


def matches_message_context(automation: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Evaluate message/stories keyword conditions for an automation."""
    eff = effective_automation_type(automation)
    if eff == "dm_keyword":
        keywords = _keywords_for_automation(automation)
        return bool(keywords) and any(
            k.lower() in (context.get("message_text", "") or "").lower() for k in keywords
        )

    if eff == "story_reaction":
        story_id = context.get("story_id")
        trigger_stories = _trigger_story_ids(automation)
        return bool(trigger_stories) and story_id in trigger_stories

    return True


def matches_comment_trigger(
    automation: Dict[str, Any], trigger_type: str, context: Dict[str, Any]
) -> bool:
    """Check trigger type, media filters, and keyword match for comments."""
    trigger = automation.get("trigger", {}) or {}
    if canonical_trigger_type(trigger.get("type")) != canonical_trigger_type(trigger_type):
        return False

    media_id = str(context.get("media_id") or "")
    post_id = trigger.get("post_id")
    if post_id and media_id and str(post_id) != media_id:
        return False

    media_ids = trigger.get("media_ids") or []
    if media_ids and media_id and media_id not in {str(x) for x in media_ids}:
        return False

    comment_text = context.get("comment_text", "") or ""
    return match_keywords(comment_text, trigger.get("keywords", []) or [])
