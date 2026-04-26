"""Comment webhook processor for handling Instagram comment events."""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from app.db.cosmos_db import cosmos_db
from app.db.cosmos_containers import (
    CONTAINER_CONTACTS,
    CONTAINER_MESSAGE_LOGS,
)
from app.db.repositories.automation_repository import (
    list_enabled_automations_for_account,
)
from app.services.automation_matcher import matches_comment_trigger
from app.services.automation_conditions import (
    apply_cooldown_from_automation,
    passes_comment_automation_conditions,
)
from app.workers.processor_utils import resolve_account_id_with_cache
from app.workers.step_delivery import run_step_on_deliver_actions

logger = logging.getLogger(__name__)


class CommentProcessor:
    """Process comment webhook events."""

    def __init__(self):
        """Initialize comment processor."""
        self.contacts_container = CONTAINER_CONTACTS
        self.message_logs_container = CONTAINER_MESSAGE_LOGS

    def process_comment_webhook(self, event: Dict[str, Any]) -> None:
        """
        Process an Instagram comment webhook event.

        Extracts comment metadata, resolves account, matches automations,
        and executes matching automation responses.
        """
        comment_data = self._extract_comment_data(event)

        if not comment_data:
            logger.warning("Unable to extract comment data from webhook")
            return

        logger.info(
            "Processing comment from user %s on media %s",
            comment_data["from_id"],
            comment_data.get("media_id"),
        )

        account_id = self._resolve_account_id(comment_data["ig_user_id"])

        if not account_id:
            logger.error(
                "Unable to resolve account for Instagram user %s",
                comment_data["ig_user_id"],
            )
            return

        matching_automations = self._match_automations(
            account_id, "comment", comment_data
        )

        if not matching_automations:
            logger.debug("No matching automations found for comment event")
            return

        logger.info("Found %s matching automations", len(matching_automations))

        for automation in matching_automations:
            self._execute_automation(automation, account_id, comment_data)

    def _extract_comment_data(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract comment data from webhook event envelope (see _enqueue_webhook_events)."""
        inner_event = event.get("event", {})
        comment_value = inner_event.get("value", {})

        if not comment_value and "text" in event:
            comment_value = event

        comment_text = comment_value.get("text", "")
        from_data = comment_value.get("from", {})
        from_id = from_data.get("id")
        from_username = from_data.get("username")
        media_data = comment_value.get("media", {})
        media_id = media_data.get("id")
        ig_account_id = event.get("ig_account_id", "")

        if not comment_text or not from_id:
            logger.warning(
                "Missing required comment fields: text=%s from_id=%s media_id=%s",
                bool(comment_text),
                from_id,
                media_id,
            )
            return None

        return {
            "comment_id": comment_value.get("id"),
            "comment_text": comment_text,
            "from_id": from_id,
            "from_username": from_username,
            "ig_user_id": ig_account_id,
            "media_id": media_id,
            "media_product_type": media_data.get("media_product_type"),
            "timestamp": event.get("webhook_timestamp", datetime.utcnow().isoformat()),
        }

    def _resolve_account_id(self, ig_user_id: str) -> Optional[str]:
        """Resolve account_id from Instagram user ID using Redis cache + Cosmos."""
        return resolve_account_id_with_cache(ig_user_id, logger)

    def _match_automations(
        self, account_id: str, trigger_type: str, context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        results = list_enabled_automations_for_account(account_id)
        matching: List[Dict[str, Any]] = []
        for automation in results:
            if automation.get("deleted_at"):
                continue
            if not self._is_matching_comment_trigger(automation, trigger_type, context):
                continue
            if not passes_comment_automation_conditions(automation, context):
                continue
            matching.append(automation)
        return matching

    def _is_matching_comment_trigger(
        self, automation: Dict[str, Any], trigger_type: str, context: Dict[str, Any]
    ) -> bool:
        return matches_comment_trigger(automation, trigger_type, context)

    def _execute_automation(
        self,
        automation: Dict[str, Any],
        account_id: str,
        comment_data: Dict[str, Any],
    ) -> None:
        automation_id = automation.get("id")
        steps = automation.get("steps", [])

        if not steps:
            logger.warning("Automation %s has no steps", automation_id)
            return

        first_step = steps[0]

        logger.info(
            "Executing automation %s, first step: %s",
            automation_id,
            first_step.get("id"),
        )

        message_context: Dict[str, Any] = {
            "automation_id": automation_id,
            "trigger_type": "comment",
            "comment_id": comment_data.get("comment_id"),
            "comment_text": comment_data.get("comment_text"),
            "from_id": comment_data.get("from_id"),
            "from_username": comment_data.get("from_username"),
            "media_id": comment_data.get("media_id"),
            "account_id": account_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Comment automation context automation_id=%s context=%s",
                automation_id,
                json.dumps(message_context, ensure_ascii=True, default=str),
            )
        self._execute_step(
            first_step,
            automation,
            account_id,
            comment_data.get("from_id"),
            message_context,
        )

    def _execute_step(
        self,
        step: Dict[str, Any],
        automation: Dict[str, Any],
        account_id: str,
        contact_id: str,
        context: Dict[str, Any],
    ) -> None:
        from app.services.message_builder import message_builder
        from app.services.instagram_api import instagram_api

        logger.info(
            "Executing step %s for contact %s",
            step.get("id"),
            contact_id,
        )

        message = message_builder.build_comment_dm_from_step(
            step, context, automation_id=automation.get("id")
        )
        if not message:
            logger.error(
                "No message from step automation_id=%s step_id=%s",
                automation.get("id"),
                step.get("id"),
            )
            return

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Step message built automation_id=%s step_id=%s message=%s",
                automation.get("id"),
                step.get("id"),
                json.dumps(message, ensure_ascii=True, default=str),
            )

        # Generic/carousel to recipient id only (Meta often rejects comment_id + template).
        instagram_api.send_dm_sync(
            account_id, contact_id, message, comment_id=None
        )
        logger.info(
            "Comment-trigger DM sent automation_id=%s step_id=%s contact_id=%s",
            automation.get("id"),
            step.get("id"),
            contact_id,
        )

        self._log_message_delivery(
            account_id, contact_id, step.get("id"), message, "sent"
        )

        run_step_on_deliver_actions(
            account_id, contact_id, step, context
        )
        apply_cooldown_from_automation(automation, str(contact_id))
        logger.info(
            "Completed on_deliver_actions automation_id=%s step_id=%s",
            automation.get("id"),
            step.get("id"),
        )

    def _log_message_delivery(
        self, account_id: str, contact_id: str, step_id: str, message: Dict[str, Any], status: str
    ) -> None:
        try:
            container = cosmos_db.get_container_client(self.message_logs_container)
            log_entry = {
                "id": f"msg_{int(datetime.utcnow().timestamp())}_{contact_id}",
                "account_id": account_id,
                "contact_id": contact_id,
                "step_id": step_id,
                "message": message,
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
            }
            container.create_item(log_entry)
        except Exception as e:
            logger.error("Error logging message delivery: %s", e, exc_info=True)


comment_processor = CommentProcessor()


def process_comment_webhook(event: Dict[str, Any]) -> None:
    """Process comment webhook event."""
    comment_processor.process_comment_webhook(event)
