"""Message builder service for Instagram API payload construction."""
import copy
import logging
import base64
import json
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class MessageBuilder:
    """
    Build Instagram API message payloads from template schemas.

    Supports:
    - text messages
    - generic templates (cards with buttons)
    - carousel templates (multiple cards)
    - postback payload encoding (for `instagram_api.send_dm` canonical format)
    """

    # ── Canonical {type, content} for instagram_api.send_dm ─────────────────

    @staticmethod
    def normalize_message_template(tpl: Any) -> Dict[str, Any]:
        """
        Normalize DB / UI shapes into {"type": "text|generic|carousel", "content": {...}}
        for Instagram API (see instagram_api._build_send_message_request).
        """
        if tpl is None:
            return {}
        if isinstance(tpl, str):
            t = tpl.strip()
            return {"type": "text", "content": {"text": t}} if t else {}
        if not isinstance(tpl, dict):
            return {}

        if tpl.get("type") and isinstance(tpl.get("content"), dict):
            return tpl

        if any(k in tpl for k in ("message_text", "message_image_url")):
            text = (tpl.get("message_text") or "").strip()
            img = (tpl.get("message_image_url") or "").strip()
            buttons = list(tpl.get("buttons") or [])
            if img or buttons:
                return {
                    "type": "generic",
                    "content": {
                        "title": text or " ",
                        "image_url": img or None,
                        "buttons": buttons,
                    },
                }
            if text:
                return {"type": "text", "content": {"text": text}}
            return {}

        msg = tpl.get("message")
        if isinstance(msg, dict) and msg.get("text"):
            return {"type": "text", "content": {"text": msg["text"]}}

        mt = tpl.get("message_type") or tpl.get("messageType")
        if mt is not None:
            mt_s = str(mt).lower().replace(" ", "_")
            if "carousel" in mt_s:
                elems = tpl.get("carousel_elements") or tpl.get("elements") or []
                return {"type": "carousel", "content": {"elements": elems}}
            if "generic" in mt_s:
                return {
                    "type": "generic",
                    "content": {
                        "title": tpl.get("generic_title") or tpl.get("title") or "",
                        "subtitle": tpl.get("generic_subtitle") or tpl.get("subtitle"),
                        "image_url": tpl.get("generic_image_url") or tpl.get("image_url"),
                        "buttons": list(tpl.get("generic_buttons") or tpl.get("buttons") or []),
                    },
                }
            tx = tpl.get("text") or tpl.get("body") or ""
            if isinstance(tx, str) and tx.strip():
                return {"type": "text", "content": {"text": tx}}

        if "text" in tpl and tpl.get("text") is not None:
            tx = tpl.get("text")
            if isinstance(tx, str) and tx.strip():
                return {"type": "text", "content": {"text": tx}}

        c = tpl.get("content")
        if isinstance(c, dict):
            if c.get("text") is not None:
                return {"type": "text", "content": {"text": str(c.get("text", ""))}}
            if c.get("elements"):
                return {"type": "carousel", "content": {"elements": c.get("elements", [])}}
            if c.get("title") is not None or c.get("buttons"):
                return {"type": "generic", "content": c}

        for key in ("body", "messageText", "caption"):
            v = tpl.get(key)
            if isinstance(v, str) and v.strip():
                return {"type": "text", "content": {"text": v}}

        if isinstance(tpl.get("message"), str) and tpl["message"].strip():
            return {"type": "text", "content": {"text": tpl["message"]}}

        return {}

    @staticmethod
    def resolve_message_template(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Resolve a step document or nested template into canonical {type, content}.

        Priority: `message` (nested) → flat `message_text` on the step → normalize whole dict.
        """
        if not data:
            return {}

        msg = data.get("message")
        if isinstance(msg, dict) and msg:
            n = MessageBuilder.normalize_message_template(msg)
            if n:
                return n

        if any(k in data for k in ("message_text", "message_image_url")):
            return MessageBuilder.normalize_message_template(data)

        return MessageBuilder.normalize_message_template(data)

    @staticmethod
    def _encode_postback_buttons(buttons: List[Dict[str, Any]], automation_id: str) -> None:
        for b in buttons:
            if (b.get("type") or "postback").lower() == "postback":
                b["payload"] = MessageBuilder.encode_postback_payload(
                    automation_id, "button_click", metadata=None
                )

    @staticmethod
    def encode_postbacks_in_canonical_template(
        template: Dict[str, Any], automation_id: str
    ) -> Dict[str, Any]:
        """Deep-copy template and encode postback button payloads for automation_id."""
        if not template or not automation_id:
            return template
        out = copy.deepcopy(template)
        t = (out.get("type") or "text").lower()
        if t == "generic":
            c = out.setdefault("content", {})
            MessageBuilder._encode_postback_buttons(c.get("buttons") or [], automation_id)
        elif t == "carousel":
            for el in out.get("content", {}).get("elements") or []:
                MessageBuilder._encode_postback_buttons(el.get("buttons") or [], automation_id)
        return out

    @staticmethod
    def _interpolate_strings(obj: Any, context: Dict[str, Any]) -> Any:
        if isinstance(obj, str):
            def repl(m):
                key = m.group(1).strip()
                return str(context.get(key, ""))

            return re.sub(r"\{\{([^}]+)\}\}", repl, obj)
        if isinstance(obj, dict):
            return {k: MessageBuilder._interpolate_strings(v, context) for k, v in obj.items()}
        if isinstance(obj, list):
            return [MessageBuilder._interpolate_strings(i, context) for i in obj]
        return obj

    def build_message(
        self,
        step_or_template: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        automation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Build payload for instagram_api.send_dm: {"type": "...", "content": {...}}.

        Accepts a full step (`message` nested, or flat `message_text` on the step) or a template dict.
        """
        resolved = MessageBuilder.resolve_message_template(step_or_template or {})
        if not resolved:
            return None
        if context:
            resolved = MessageBuilder._interpolate_strings(resolved, context)
        if automation_id:
            resolved = MessageBuilder.encode_postbacks_in_canonical_template(
                resolved, automation_id
            )
        return resolved

    @staticmethod
    def encode_postback_payload(
        automation_id: str,
        action: str,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Base64-encode postback payload data.

        Postback data structure:
        {
            "automation_id": "...",
            "action": "click_button",
            "step_id": "...",
            "metadata": {...}
        }

        Args:
            automation_id: Automation ID this postback belongs to
            action: Action type (e.g., 'click_button', 'select_option')
            step_id: Optional step ID in automation flow
            metadata: Optional additional data

        Returns:
            Base64-encoded JSON payload string
        """
        try:
            payload_data = {
                "automation_id": automation_id,
                "action": action
            }

            if step_id:
                payload_data["step_id"] = step_id
            if metadata:
                payload_data["metadata"] = metadata

            json_str = json.dumps(payload_data)
            encoded = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

            logger.debug(f"Encoded postback payload: automation_id={automation_id}, action={action}")
            return encoded

        except Exception as e:
            logger.error(f"Error encoding postback payload: {str(e)}")
            raise


# Global singleton instance
message_builder = MessageBuilder()
