"""Comment webhook processor for handling Instagram comment events."""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class CommentProcessor:
    """Process comment webhook events."""

    def __init__(self):
        """Initialize comment processor."""
        self.automations_container = dm_settings.DM_AUTOMATIONS_CONTAINER
        self.contacts_container = dm_settings.DM_CONTACTS_CONTAINER
        self.message_logs_container = dm_settings.DM_MESSAGE_LOGS_CONTAINER
        self.automation_cache_ttl = dm_settings.AUTOMATION_CACHE_TTL_HOURS * 3600

    def process_comment_webhook(self, event: Dict[str, Any]) -> None:
        """
        Process an Instagram comment webhook event.

        Extracts comment metadata, resolves account, matches automations,
        and executes matching automation responses.

        Args:
            event: Comment webhook event payload
        """
        try:
            # Extract comment data from webhook
            comment_data = self._extract_comment_data(event)

            if not comment_data:
                logger.warning("Unable to extract comment data from webhook")
                return

            logger.info(
                f"Processing comment from user {comment_data['from_id']} "
                f"on media {comment_data['media_id']}"
            )

            # Resolve account_id via Redis cache
            account_id = self._resolve_account_id(comment_data["ig_user_id"])

            if not account_id:
                logger.error(
                    f"Unable to resolve account for Instagram user {comment_data['ig_user_id']}"
                )
                return

            # Load and match automations
            matching_automations = self._match_automations(
                account_id, "comment", comment_data
            )

            if not matching_automations:
                logger.debug(f"No matching automations found for comment event")
                return

            logger.info(f"Found {len(matching_automations)} matching automations")

            # Execute matched automations
            for automation in matching_automations:
                self._execute_automation(automation, account_id, comment_data)

        except Exception as e:
            logger.exception(f"Error processing comment webhook: {str(e)}")
            raise

    def _extract_comment_data(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract comment data from webhook payload.

        Args:
            event: Webhook event payload

        Returns:
            Extracted comment data or None
        """
        try:
            comment_text = event.get("text", "")
            from_id = event.get("from", {}).get("id")
            media_id = event.get("media", {}).get("id")

            if not all([comment_text, from_id, media_id]):
                logger.warning(
                    "Missing required comment fields: "
                    f"text={bool(comment_text)}, from_id={from_id}, media_id={media_id}"
                )
                return None

            return {
                "comment_id": event.get("id"),
                "comment_text": comment_text,
                "from_id": from_id,
                "ig_user_id": from_id,  # Instagram user ID
                "media_id": media_id,
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
            }

        except Exception as e:
            logger.error(f"Error extracting comment data: {str(e)}")
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

            # Query Cosmos DB for account mapping
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

            logger.debug(f"Resolved account {account_id} for Instagram user {ig_user_id}")
            return account_id

        except Exception as e:
            logger.error(f"Error resolving account ID: {str(e)}")
            return None

    def _match_automations(
        self, account_id: str, trigger_type: str, context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Load and match automations based on trigger type and context.

        Args:
            account_id: Account ID
            trigger_type: Trigger type (e.g., "comment")
            context: Event context data

        Returns:
            List of matching automation configurations
        """
        try:
            container = cosmos_db.get_container_client(self.automations_container)

            # Query for active automations with comment trigger
            query = (
                "SELECT c.* FROM c "
                "WHERE c.account_id = @account_id "
                "AND c.status = 'active' "
                "AND ARRAY_CONTAINS(c.triggers, @trigger_type)"
            )

            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@account_id", "value": account_id},
                        {"name": "@trigger_type", "value": trigger_type},
                    ],
                )
            )

            # Filter automations based on conditions
            matching = []
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
        Check if automation conditions match the event context.

        Args:
            automation: Automation configuration
            context: Event context

        Returns:
            True if conditions match
        """
        try:
            conditions = automation.get("trigger_conditions", [])

            if not conditions:
                return True

            # Check each condition
            for condition in conditions:
                field = condition.get("field", "")
                match_type = condition.get("match_type", "equals")
                value = condition.get("value", "")

                context_value = context.get(field, "")

                if not self._check_condition(context_value, match_type, value):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking automation conditions: {str(e)}")
            return False

    def _check_condition(self, context_value: Any, match_type: str, expected_value: Any) -> bool:
        """
        Check a single condition.

        Args:
            context_value: Value from context
            match_type: Type of match (equals, contains, starts_with, etc.)
            expected_value: Expected value

        Returns:
            True if condition matches
        """
        try:
            context_str = str(context_value).lower()
            expected_str = str(expected_value).lower()

            if match_type == "equals":
                return context_str == expected_str
            elif match_type == "contains":
                return expected_str in context_str
            elif match_type == "starts_with":
                return context_str.startswith(expected_str)
            elif match_type == "ends_with":
                return context_str.endswith(expected_str)
            elif match_type == "regex":
                import re

                return bool(re.search(expected_str, context_str))
            else:
                return False

        except Exception as e:
            logger.error(f"Error checking condition: {str(e)}")
            return False

    def _execute_automation(
        self,
        automation: Dict[str, Any],
        account_id: str,
        comment_data: Dict[str, Any],
    ) -> None:
        """
        Execute an automation in response to the comment.

        Args:
            automation: Automation configuration
            account_id: Account ID
            comment_data: Comment data
        """
        try:
            automation_id = automation.get("id")
            steps = automation.get("steps", [])

            if not steps:
                logger.warning(f"Automation {automation_id} has no steps")
                return

            # Get the first step
            first_step = steps[0]

            logger.info(
                f"Executing automation {automation_id}, first step: {first_step.get('id')}"
            )

            # Build message context
            message_context = {
                "automation_id": automation_id,
                "trigger_type": "comment",
                "comment_id": comment_data.get("comment_id"),
                "comment_text": comment_data.get("comment_text"),
                "from_id": comment_data.get("from_id"),
                "account_id": account_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Execute the step
            self._execute_step(
                first_step,
                automation,
                account_id,
                comment_data.get("from_id"),
                message_context,
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
            contact_id: Contact/user ID
            context: Execution context
        """
        try:
            # This is a simplified version - full implementation would handle
            # message building, sending, and on_deliver_actions
            logger.info(
                f"Executing step {step.get('id')} for contact {contact_id}"
            )

            # Import here to avoid circular dependencies
            from app.services.message_builder import message_builder
            from app.services.instagram_api import instagram_api

            # Build message
            message_template = step.get("message_template", {})
            message = message_builder.build_message(message_template, context)

            # Send message
            if message:
                instagram_api.send_dm(account_id, contact_id, message)

                # Log message delivery
                self._log_message_delivery(
                    account_id, contact_id, step.get("id"), message, "sent"
                )

        except Exception as e:
            logger.exception(f"Error executing step: {str(e)}")

    def _log_message_delivery(
        self, account_id: str, contact_id: str, step_id: str, message: Dict[str, Any], status: str
    ) -> None:
        """
        Log message delivery to analytics.

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
comment_processor = CommentProcessor()


def process_comment_webhook(event: Dict[str, Any]) -> None:
    """
    Process comment webhook event.

    Args:
        event: Webhook event payload
    """
    comment_processor.process_comment_webhook(event)
