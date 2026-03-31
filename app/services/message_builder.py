"""Message builder service for Instagram API payload construction."""
import logging
import base64
import json
from typing import Dict, Any, List, Optional

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
