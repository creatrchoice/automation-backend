"""Message builder service for Instagram API payload construction."""
import copy
import logging
import base64
import json
import re
from typing import Dict, Any, List, Optional

from app.core.config import dm_settings

logger = logging.getLogger(__name__)


class MessageBuilder:
    """
    Build Instagram API message payloads from template schemas.

    Supports:
    - text messages
    - generic templates (cards with buttons)
    - carousel templates (multiple cards)
    - Postback payload encoding/decoding
    """

    # Instagram API message type constants
    MESSAGE_TYPE_TEXT = "text"
    MESSAGE_TYPE_GENERIC = "generic"
    MESSAGE_TYPE_CAROUSEL = "carousel"

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
    def coerce_to_text_for_comment_private_reply(
        msg: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Private replies to comments use the messaging API with recipient.comment_id.
        Meta often rejects generic/carousel there (e.g. IGApiException 2018340). Use a
        plain text body so at least one DM delivers; include title/subtitle content.
        """
        if not msg:
            return msg
        mtype = (msg.get("type") or "text").lower()
        if mtype == "text":
            return msg

        content = msg.get("content") or {}
        text_out = ""

        if mtype == "generic":
            title = (content.get("title") or "").strip()
            subtitle = (content.get("subtitle") or "").strip()
            lines = [x for x in (title, subtitle) if x]
            text_out = "\n".join(lines) if lines else (title or subtitle or " ")
        elif mtype == "carousel":
            elements = content.get("elements") or []
            parts: List[str] = []
            for el in elements[:12]:
                if not isinstance(el, dict):
                    continue
                t = (el.get("title") or "").strip()
                s = (el.get("subtitle") or "").strip()
                block = t + (f"\n{s}" if s else "")
                if block.strip():
                    parts.append(block.strip())
            text_out = "\n\n".join(parts) if parts else " "
        else:
            return msg

        text_out = (text_out or " ").strip() or " "
        if len(text_out) > dm_settings.MAX_MESSAGE_LENGTH:
            text_out = text_out[: dm_settings.MAX_MESSAGE_LENGTH - 1] + "…"

        logger.info(
            "Coerced %s template to plain text for Instagram comment private reply",
            mtype,
        )
        return {"type": "text", "content": {"text": text_out}}

    @staticmethod
    def resolve_message_template(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Resolve a step document or nested template into canonical {type, content}.

        Priority: message_template / template → message (nested) → flat message_text → normalize whole dict.
        """
        if not data:
            return {}

        for key in ("message_template", "messageTemplate", "template"):
            v = data.get(key)
            if isinstance(v, dict) and v:
                n = MessageBuilder.normalize_message_template(v)
                if n:
                    return n

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

        Accepts a full step (message_text, message_template, …) or a nested template dict.
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
    def build_message_payload(template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert message template schema to Instagram API payload format.

        Args:
            template: Message template dict with structure:
                {
                    "type": "text|generic|carousel",
                    "content": {...}  # varies by type
                }

        Returns:
            Instagram API message payload

        Raises:
            ValueError: If template type is unsupported
        """
        try:
            template_type = template.get("type", "text").lower()
            content = template.get("content", {})

            if template_type == "text":
                return MessageBuilder._build_text_payload(content)
            elif template_type == "generic":
                return MessageBuilder._build_generic_payload(content)
            elif template_type == "carousel":
                return MessageBuilder._build_carousel_payload(content)
            else:
                raise ValueError(f"Unsupported template type: {template_type}")

        except Exception as e:
            logger.error(f"Error building message payload: {str(e)}")
            raise

    @staticmethod
    def _build_text_payload(content: Dict[str, Any]) -> Dict[str, Any]:
        """Build text message payload."""
        text = content.get("text", "")
        if not text:
            raise ValueError("Text message missing 'text' field")

        return {
            "messaging_type": "MESSAGE_TYPE_RESPONSE",
            "recipient": {"id": "{recipient_id}"},
            "message": {
                "text": text
            }
        }

    @staticmethod
    def _build_generic_payload(content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build generic template payload (single card with buttons/actions).

        Content schema:
        {
            "title": "...",
            "subtitle": "...",
            "image_url": "...",
            "buttons": [
                {
                    "type": "postback|web_url|call",
                    "title": "Button Text",
                    "payload|url|phone_number": "..."
                }
            ]
        }
        """
        buttons = MessageBuilder._build_buttons(content.get("buttons", []))

        element = {
            "title": content.get("title", ""),
            "buttons": buttons
        }

        if content.get("subtitle"):
            element["subtitle"] = content["subtitle"]
        if content.get("image_url"):
            element["image_url"] = content["image_url"]

        return {
            "messaging_type": "MESSAGE_TYPE_RESPONSE",
            "recipient": {"id": "{recipient_id}"},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [element]
                    }
                }
            }
        }

    @staticmethod
    def _build_carousel_payload(content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build carousel template payload (multiple cards).

        Content schema:
        {
            "elements": [
                {
                    "title": "...",
                    "subtitle": "...",
                    "image_url": "...",
                    "buttons": [...]
                },
                ...
            ]
        }
        """
        elements = content.get("elements", [])
        if not elements:
            raise ValueError("Carousel template requires 'elements'")

        carousel_elements = []
        for elem in elements:
            buttons = MessageBuilder._build_buttons(elem.get("buttons", []))

            carousel_elem = {
                "title": elem.get("title", ""),
                "buttons": buttons
            }

            if elem.get("subtitle"):
                carousel_elem["subtitle"] = elem["subtitle"]
            if elem.get("image_url"):
                carousel_elem["image_url"] = elem["image_url"]

            carousel_elements.append(carousel_elem)

        return {
            "messaging_type": "MESSAGE_TYPE_RESPONSE",
            "recipient": {"id": "{recipient_id}"},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": carousel_elements
                    }
                }
            }
        }

    @staticmethod
    def _build_buttons(buttons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build button array for generic/carousel payloads."""
        ig_buttons = []

        for btn in buttons:
            btn_type = btn.get("type", "postback").lower()

            if btn_type == "postback":
                ig_buttons.append({
                    "type": "postback",
                    "title": btn.get("title", ""),
                    "payload": btn.get("payload", "")
                })
            elif btn_type == "web_url":
                ig_buttons.append({
                    "type": "web_url",
                    "title": btn.get("title", ""),
                    "url": btn.get("url", "")
                })
            elif btn_type == "call":
                ig_buttons.append({
                    "type": "phone_number",
                    "title": btn.get("title", ""),
                    "payload": btn.get("phone_number", "")
                })

        return ig_buttons

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

    @staticmethod
    def decode_postback_payload(payload_str: str) -> Dict[str, Any]:
        """
        Base64-decode and parse postback payload.

        Args:
            payload_str: Base64-encoded payload string

        Returns:
            Decoded payload dictionary

        Raises:
            ValueError: If payload is invalid or not base64
        """
        try:
            decoded_str = base64.b64decode(payload_str.encode("utf-8")).decode("utf-8")
            data = json.loads(decoded_str)

            logger.debug(f"Decoded postback payload: {data}")
            return data

        except Exception as e:
            logger.error(f"Error decoding postback payload: {str(e)}")
            raise ValueError(f"Invalid postback payload: {str(e)}")

    @staticmethod
    def build_message_with_postback_payloads(
        template: Dict[str, Any],
        automation_id: str
    ) -> Dict[str, Any]:
        """
        Build message payload and encode all button postbacks.

        Processes all buttons in the template (generic or carousel):
        - For postback buttons: encodes the payload with automation_id
        - For web_url and call buttons: leaves unchanged

        Args:
            template: Message template (as from build_message_payload)
            automation_id: Automation ID to encode in postback payloads

        Returns:
            Modified payload with encoded postback payloads
        """
        try:
            # First build the base payload
            payload = MessageBuilder.build_message_payload(template)

            # Process buttons if they exist
            message_obj = payload.get("message", {})
            attachment = message_obj.get("attachment")

            if attachment and attachment.get("type") == "template":
                template_payload = attachment.get("payload", {})
                elements = template_payload.get("elements", [])

                for element in elements:
                    buttons = element.get("buttons", [])
                    for button in buttons:
                        if button.get("type") == "postback":
                            # Encode existing payload or create new one
                            existing_payload = button.get("payload", "")
                            metadata = None

                            # Try to decode existing payload to extract metadata
                            if existing_payload and existing_payload.startswith("{"):
                                try:
                                    metadata = json.loads(existing_payload)
                                except json.JSONDecodeError:
                                    pass

                            # Encode with automation_id
                            button["payload"] = MessageBuilder.encode_postback_payload(
                                automation_id=automation_id,
                                action="button_click",
                                metadata=metadata
                            )

            logger.debug(f"Built message with postback payloads for automation {automation_id}")
            return payload

        except Exception as e:
            logger.error(f"Error building message with postback payloads: {str(e)}")
            raise


# Global singleton instance
message_builder = MessageBuilder()
