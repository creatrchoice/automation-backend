"""DM message webhook processor for handling incoming direct messages."""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class MessageSourceType(str, Enum):
    """Source type for incoming messages."""
    TEXT = "text"
    MEDIA_SHARE = "media_share"
    STORY_REPLY = "story_reply"
    UNKNOWN = "unknown"


class MessageProcessor:
    """Process incoming DM webhook events."""

    def __init__(self):
        """Initialize message processor."""
        self.automations_container = dm_settings.DM_AUTOMATIONS_CONTAINER
        self.contacts_container = dm_settings.DM_CONTACTS_CONTAINER
        self.message_logs_container = dm_settings.DM_MESSAGE_LOGS_CONTAINER

    def process_message_webhook(self, event: Dict[str, Any]) -> None:
        """
        Process an incoming DM webhook event.

        Detects message type (text, media share, story reply), matches against
        automations, and handles human handoff.

        Args:
            event: Message webhook event payload
        """
        try:
            # Extract message data from webhook
            message_data = self._extract_message_data(event)

            if not message_data:
                logger.warning("Unable to extract message data from webhook")
                return

            logger.info(
                f"Processing message from contact {message_data['from_id']}, "
                f"type: {message_data['message_type']}"
            )

            # Resolve account_id
            account_id = self._resolve_account_id(message_data["ig_user_id"])

            if not account_id:
                logger.error(
                    f"Unable to resolve account for Instagram user {message_data['ig_user_id']}"
                )
                return

            # Update contact's messaging window
            self._refresh_messaging_window(account_id, message_data["from_id"])

            # Load and match automations
            matching_automations = self._match_automations(
                account_id, message_data["message_type"], message_data
            )

            if matching_automations:
                logger.info(f"Found {len(matching_automations)} matching automations")

                # Execute matched automations
                for automation in matching_automations:
                    self._execute_automation(automation, account_id, message_data)

            else:
                # Check for human handoff if contact has active automation
                self._check_human_handoff(account_id, message_data)

        except Exception as e:
            logger.exception(f"Error processing message webhook: {str(e)}")
            raise

    def _extract_message_data(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract message data from webhook payload.

        Args:
            event: Webhook event payload

        Returns:
            Extracted message data or None
        """
        try:
            message = event.get("message", {})
            from_id = event.get("from", {}).get("id")

            if not from_id:
                logger.warning("Missing 'from' ID in webhook event")
                return None

            # Detect message source type
            message_type = self._detect_message_type(message)

            # Extract message text
            message_text = ""
            if message_type == MessageSourceType.TEXT:
                message_text = message.get("text", "")
            elif message_type == MessageSourceType.STORY_REPLY:
                message_text = message.get("text", "")

            return {
                "message_id": message.get("mid"),
                "from_id": from_id,
                "ig_user_id": from_id,
                "message_text": message_text,
                "message_type": message_type.value,
                "media": message.get("attachments", {}).get("media"),
                "story_id": self._extract_story_id(message) if message_type == MessageSourceType.STORY_REPLY else None,
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
            }

        except Exception as e:
            logger.error(f"Error extracting message data: {str(e)}")
            return None

    def _detect_message_type(self, message: Dict[str, Any]) -> MessageSourceType:
        """
        Detect the type of incoming message.

        Args:
            message: Message object from webhook

        Returns:
            MessageSourceType enum
        """
        try:
            # Check for story reply
            if message.get("reply_to", {}).get("story"):
                return MessageSourceType.STORY_REPLY

            # Check for media share
            if message.get("attachments"):
                attachments = message.get("attachments", {})
                if attachments.get("media") or attachments.get("video"):
                    return MessageSourceType.MEDIA_SHARE

            # Default to text
            if message.get("text"):
                return MessageSourceType.TEXT

            return MessageSourceType.UNKNOWN

        except Exception as e:
            logger.error(f"Error detecting message type: {str(e)}")
            return MessageSourceType.UNKNOWN

    def _extract_story_id(self, message: Dict[str, Any]) -> Optional[str]:
        """
        Extract story ID from message if it's a story reply.

        Args:
            message: Message object

        Returns:
            Story ID or None
        """
        try:
            return message.get("reply_to", {}).get("story", {}).get("id")
        except Exception as e:
            logger.error(f"Error extracting story ID: {str(e)}")
            return None

    def _resolve_account_id(self, ig_user_id: str) -> Optional[str]:
        """
        Resolve account_id from Instagram user ID using Redis cache.

        Args:
            ig_user_id: Instagram user ID

        Returns:
            Account ID or None
        """
        try:
            cache_key = f"account_map:{ig_user_id}"

            # Try cache first
            cached_account_id = redis_client.get(cache_key)
            if cached_account_id:
                logger.debug(f"Found account mapping in cache for {ig_user_id}")
                return cached_account_id

            # Query Cosmos DB
            container = cosmos_db.get_container_client(
                dm_settings.DM_IG_ACCOUNTS_CONTAINER
            )
            query = "SELECT c.account_id FROM c WHERE c.ig_user_id = @ig_user_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[{"name": "@ig_user_id", "value": ig_user_id}],
                )
            )

            if not results:
                logger.warning(f"No account found for Instagram user {ig_user_id}")
                return None

            account_id = results[0].get("account_id")

            # Cache the mapping
            cache_ttl = dm_settings.ACCOUNT_MAP_CACHE_TTL_HOURS * 3600
            redis_client.setex(cache_key, cache_ttl, account_id)

            return account_id

        except Exception as e:
            logger.error(f"Error resolving account ID: {str(e)}")
            return None

    def _refresh_messaging_window(self, account_id: str, contact_id: str) -> None:
        """
        Refresh the 24-hour messaging window for a contact.

        Args:
            account_id: Account ID
            contact_id: Contact ID
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            # Query contact
            query = "SELECT c.id FROM c WHERE c.id = @contact_id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@contact_id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                logger.debug(f"Contact {contact_id} not found, may be new")
                return

            # Update messaging window expiration
            contact = results[0]
            window_hours = dm_settings.MESSAGING_WINDOW_HOURS
            new_window_expires = datetime.utcnow()
            new_window_expires = new_window_expires.replace(
                hour=(new_window_expires.hour + window_hours) % 24
            )

            # Update contact (simplified - full implementation would be more robust)
            contact["messaging_window_expires"] = new_window_expires.isoformat()
            contact["last_message_received_at"] = datetime.utcnow().isoformat()

            container.replace_item(contact["id"], contact)
            logger.debug(f"Refreshed messaging window for contact {contact_id}")

        except Exception as e:
            logger.error(f"Error refreshing messaging window: {str(e)}")

    def _match_automations(
        self, account_id: str, message_type: str, context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Load and match automations based on message type and content.

        Args:
            account_id: Account ID
            message_type: Type of message
            context: Message context

        Returns:
            List of matching automations
        """
        try:
            container = cosmos_db.get_container_client(self.automations_container)
            matching = []

            # Determine automation types to search
            search_types = []
            if message_type == "text":
                search_types = ["dm_keyword", "message_received"]
            elif message_type == "story_reply":
                search_types = ["story_reaction", "message_received"]
            elif message_type == "media_share":
                search_types = ["message_received"]

            for automation_type in search_types:
                query = (
                    "SELECT c.* FROM c "
                    "WHERE c.account_id = @account_id "
                    "AND c.status = 'active' "
                    "AND c.automation_type = @type"
                )

                results = list(
                    container.query_items(
                        query=query,
                        parameters=[
                            {"name": "@account_id", "value": account_id},
                            {"name": "@type", "value": automation_type},
                        ],
                    )
                )

                # Filter based on conditions
                for automation in results:
                    if self._matches_automation_conditions(automation, context):
                        matching.append(automation)

            return matching

        except Exception as e:
            logger.error(f"Error matching automations: {str(e)}")
            return []

    def _matches_automation_conditions(
        self, automation: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """
        Check if automation conditions match the context.

        Args:
            automation: Automation configuration
            context: Message context

        Returns:
            True if conditions match
        """
        try:
            # For keyword-based automations, check keywords
            if automation.get("automation_type") == "dm_keyword":
                keywords = automation.get("keywords", [])
                message_text = context.get("message_text", "").lower()

                for keyword in keywords:
                    if keyword.lower() in message_text:
                        return True

                return False

            # For story-based automations
            if automation.get("automation_type") == "story_reaction":
                story_id = context.get("story_id")
                trigger_stories = automation.get("trigger_stories", [])

                if story_id in trigger_stories:
                    return True

                return False

            # Default match
            return True

        except Exception as e:
            logger.error(f"Error checking automation conditions: {str(e)}")
            return False

    def _execute_automation(
        self,
        automation: Dict[str, Any],
        account_id: str,
        message_data: Dict[str, Any],
    ) -> None:
        """
        Execute an automation in response to the message.

        Args:
            automation: Automation configuration
            account_id: Account ID
            message_data: Message data
        """
        try:
            automation_id = automation.get("id")
            steps = automation.get("steps", [])

            if not steps:
                logger.warning(f"Automation {automation_id} has no steps")
                return

            first_step = steps[0]
            logger.info(f"Executing automation {automation_id}")

            # Build execution context
            context = {
                "automation_id": automation_id,
                "trigger_type": "message",
                "message_id": message_data.get("message_id"),
                "message_text": message_data.get("message_text"),
                "from_id": message_data.get("from_id"),
                "account_id": account_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Execute first step
            self._execute_step(
                first_step,
                automation,
                account_id,
                message_data.get("from_id"),
                context,
            )

        except Exception as e:
            logger.exception(f"Error executing automation: {str(e)}")

    def _execute_step(
        self,
        step: Dict[str, Any],
        automation: Dict[str, Any],
        account_id: str,
        contact_id: str,
        context: Dict[str, Any],
    ) -> None:
        """
        Execute a single automation step.

        Args:
            step: Step configuration
            automation: Parent automation
            account_id: Account ID
            contact_id: Contact ID
            context: Execution context
        """
        try:
            from app.services.message_builder import message_builder
            from app.services.instagram_api import instagram_api

            logger.info(f"Executing step {step.get('id')}")

            # Build and send message
            message_template = step.get("message_template", {})
            message = message_builder.build_message(message_template, context)

            if message:
                instagram_api.send_dm(account_id, contact_id, message)
                self._log_message_delivery(
                    account_id, contact_id, step.get("id"), message, "sent"
                )

        except Exception as e:
            logger.exception(f"Error executing step: {str(e)}")

    def _check_human_handoff(
        self, account_id: str, message_data: Dict[str, Any]
    ) -> None:
        """
        Check if conversation should be handed off to human.

        If no automation matched and contact has active automation, flag for manual reply.

        Args:
            account_id: Account ID
            message_data: Message data
        """
        try:
            contact_id = message_data.get("from_id")
            container = cosmos_db.get_container_client(self.contacts_container)

            # Query contact to check if automation is active
            query = (
                "SELECT c.* FROM c "
                "WHERE c.id = @contact_id AND c.account_id = @account_id LIMIT 1"
            )
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@contact_id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                return

            contact = results[0]

            # Check if contact has active automation
            if contact.get("last_automation_triggered_at"):
                logger.info(
                    f"Contact {contact_id} has active automation, "
                    f"no matching automation found. Flagging for human handoff."
                )

                # Mark for manual reply
                contact["human_handoff_active"] = True
                contact["human_handoff_at"] = datetime.utcnow().isoformat()
                contact["human_handoff_notes"] = (
                    f"No automation matched. "
                    f"Incoming message: {message_data.get('message_text', '')[:100]}"
                )

                container.replace_item(contact["id"], contact)

                # Push WebSocket notification for manual reply
                self._notify_human_handoff(account_id, contact_id, message_data)

        except Exception as e:
            logger.error(f"Error checking human handoff: {str(e)}")

    def _notify_human_handoff(
        self, account_id: str, contact_id: str, message_data: Dict[str, Any]
    ) -> None:
        """
        Send WebSocket notification for human handoff.

        Args:
            account_id: Account ID
            contact_id: Contact ID
            message_data: Message data
        """
        try:
            # This would integrate with WebSocket handler
            # For now, just log
            logger.info(
                f"Handoff notification queued for account {account_id}, "
                f"contact {contact_id}"
            )

        except Exception as e:
            logger.error(f"Error sending handoff notification: {str(e)}")

    def _log_message_delivery(
        self,
        account_id: str,
        contact_id: str,
        step_id: str,
        message: Dict[str, Any],
        status: str,
    ) -> None:
        """
        Log message delivery.

        Args:
            account_id: Account ID
            contact_id: Contact ID
            step_id: Step ID
            message: Message content
            status: Delivery status
        """
        try:
            container = cosmos_db.get_container_client(self.message_logs_container)

            log_entry = {
                "id": f"msg_{int(datetime.utcnow().timestamp())}_{contact_id}",
                "partition_key": "message_log",
                "account_id": account_id,
                "contact_id": contact_id,
                "step_id": step_id,
                "message": message,
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
            }

            container.create_item(log_entry)

        except Exception as e:
            logger.error(f"Error logging message delivery: {str(e)}")


# Global processor instance
message_processor = MessageProcessor()


def process_message_webhook(event: Dict[str, Any]) -> None:
    """
    Process message webhook event.

    Args:
        event: Webhook event payload
    """
    message_processor.process_message_webhook(event)
