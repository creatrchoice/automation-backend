"""Postback button click processor for handling automation step progression."""
import logging
import base64
import json
from typing import Dict, Any, Optional
from datetime import datetime
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db
from app.db.redis import redis_client
from app.workers.actions import execute_on_deliver_action

logger = logging.getLogger(__name__)


class PostbackProcessor:
    """Process postback button click events."""

    def __init__(self):
        """Initialize postback processor."""
        self.automations_container = dm_settings.DM_AUTOMATIONS_CONTAINER
        self.contacts_container = dm_settings.DM_CONTACTS_CONTAINER
        self.message_logs_container = dm_settings.DM_MESSAGE_LOGS_CONTAINER

    def process_postback_webhook(self, event: Dict[str, Any]) -> None:
        """
        Process a postback button click webhook event.

        Decodes payload, loads automation, executes next step with conditions,
        and handles on-deliver actions.

        Args:
            event: Postback webhook event payload
        """
        try:
            # Extract postback data
            postback_data = self._extract_postback_data(event)

            if not postback_data:
                logger.warning("Unable to extract postback data from webhook")
                return

            logger.info(
                f"Processing postback from contact {postback_data['contact_id']}, "
                f"automation: {postback_data['automation_id']}"
            )

            # Resolve account_id
            account_id = self._resolve_account_id(postback_data["ig_user_id"])

            if not account_id:
                logger.error("Unable to resolve account ID")
                return

            # Decode and validate postback payload
            payload_data = self._decode_postback_payload(postback_data["payload"])

            if not payload_data:
                logger.error("Failed to decode postback payload")
                return

            # Load automation
            automation = self._load_automation(
                account_id, payload_data["automation_id"]
            )

            if not automation:
                logger.error(f"Automation {payload_data['automation_id']} not found")
                return

            # Get next step
            next_step = self._get_next_step(
                automation, payload_data["next_step_id"]
            )

            if not next_step:
                logger.warning(f"Next step {payload_data['next_step_id']} not found")
                return

            # Refresh 24-hour messaging window
            self._refresh_messaging_window(account_id, postback_data["contact_id"])

            # Execute pre-actions
            self._execute_pre_actions(next_step, account_id, postback_data)

            # Resolve branch conditions
            resolved_message = self._resolve_branch_conditions(
                next_step, account_id, postback_data
            )

            if resolved_message:
                # Send next message
                self._send_message(
                    account_id,
                    postback_data["contact_id"],
                    resolved_message,
                    automation,
                    next_step,
                    postback_data,
                )

                # Execute on-deliver actions
                self._execute_on_deliver_actions(
                    next_step, account_id, postback_data["contact_id"]
                )

            # Track button click analytics
            self._track_button_click(
                account_id,
                postback_data,
                automation,
                next_step,
            )

            logger.info("Postback processing completed successfully")

        except Exception as e:
            logger.exception(f"Error processing postback webhook: {str(e)}")
            raise

    def _extract_postback_data(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract postback data from webhook payload.

        Args:
            event: Webhook event payload

        Returns:
            Extracted postback data or None
        """
        try:
            postback = event.get("postback", {})
            from_id = event.get("from", {}).get("id")
            messaging_type = event.get("messaging_type")

            if not from_id:
                logger.warning("Missing 'from' ID in postback event")
                return None

            return {
                "contact_id": from_id,
                "ig_user_id": from_id,
                "payload": postback.get("payload", ""),
                "title": postback.get("title", ""),
                "messaging_type": messaging_type,
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
            }

        except Exception as e:
            logger.error(f"Error extracting postback data: {str(e)}")
            return None

    def _resolve_account_id(self, ig_user_id: str) -> Optional[str]:
        """
        Resolve account_id from Instagram user ID.

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
                return None

            account_id = results[0].get("account_id")

            # Cache
            cache_ttl = dm_settings.ACCOUNT_MAP_CACHE_TTL_HOURS * 3600
            redis_client.setex(cache_key, cache_ttl, account_id)

            return account_id

        except Exception as e:
            logger.error(f"Error resolving account ID: {str(e)}")
            return None

    def _decode_postback_payload(self, payload_str: str) -> Optional[Dict[str, Any]]:
        """
        Decode base64-encoded postback payload.

        Args:
            payload_str: Base64-encoded payload string

        Returns:
            Decoded payload or None
        """
        try:
            if not payload_str:
                return None

            decoded = base64.b64decode(payload_str).decode("utf-8")
            payload_data = json.loads(decoded)

            return {
                "automation_id": payload_data.get("automation_id"),
                "action": payload_data.get("action"),
                "next_step_id": payload_data.get("next_step_id"),
                "metadata": payload_data.get("metadata", {}),
            }

        except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Error decoding postback payload: {str(e)}")
            return None

    def _load_automation(self, account_id: str, automation_id: str) -> Optional[Dict[str, Any]]:
        """
        Load automation from Cosmos DB.

        Args:
            account_id: Account ID
            automation_id: Automation ID

        Returns:
            Automation configuration or None
        """
        try:
            container = cosmos_db.get_container_client(self.automations_container)

            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": automation_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                return None

            return results[0]

        except Exception as e:
            logger.error(f"Error loading automation: {str(e)}")
            return None

    def _get_next_step(
        self, automation: Dict[str, Any], next_step_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the next step from automation steps dict.

        Args:
            automation: Automation configuration
            next_step_id: ID of next step

        Returns:
            Step configuration or None
        """
        try:
            steps = automation.get("steps", {})

            if isinstance(steps, list):
                # If steps is a list
                for step in steps:
                    if step.get("id") == next_step_id:
                        return step
            else:
                # If steps is a dict with IDs as keys
                return steps.get(next_step_id)

            logger.warning(f"Step {next_step_id} not found in automation")
            return None

        except Exception as e:
            logger.error(f"Error getting next step: {str(e)}")
            return None

    def _refresh_messaging_window(self, account_id: str, contact_id: str) -> None:
        """
        Refresh 24-hour messaging window after button click.

        Args:
            account_id: Account ID
            contact_id: Contact ID
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if results:
                contact = results[0]
                window_hours = dm_settings.MESSAGING_WINDOW_HOURS
                new_expiration = datetime.utcnow()
                new_expiration = new_expiration.replace(
                    hour=(new_expiration.hour + window_hours) % 24
                )

                contact["messaging_window_expires"] = new_expiration.isoformat()
                container.replace_item(contact["id"], contact)
                logger.debug(f"Refreshed messaging window for {contact_id}")

        except Exception as e:
            logger.error(f"Error refreshing messaging window: {str(e)}")

    def _execute_pre_actions(
        self, step: Dict[str, Any], account_id: str, postback_data: Dict[str, Any]
    ) -> None:
        """
        Execute pre-actions before sending next message.

        Pre-actions: recheck_follow_status, etc.

        Args:
            step: Step configuration
            account_id: Account ID
            postback_data: Postback data
        """
        try:
            pre_actions = step.get("pre_actions", [])

            for action in pre_actions:
                action_type = action.get("type")
                logger.debug(f"Executing pre-action: {action_type}")

                if action_type == "recheck_follow_status":
                    self._recheck_follow_status(account_id, postback_data["contact_id"])

                # Add other pre-actions as needed

        except Exception as e:
            logger.error(f"Error executing pre-actions: {str(e)}")

    def _recheck_follow_status(self, account_id: str, contact_id: str) -> None:
        """
        Recheck and update contact's follow status.

        Args:
            account_id: Account ID
            contact_id: Contact ID
        """
        try:
            from app.services.instagram_api import instagram_api

            # Get follow status from Instagram API
            is_follower = instagram_api.check_follow_status(account_id, contact_id)

            # Update contact
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if results:
                contact = results[0]
                contact["custom_fields"] = contact.get("custom_fields", {})
                contact["custom_fields"]["is_follower"] = is_follower
                container.replace_item(contact["id"], contact)
                logger.debug(f"Updated follow status for {contact_id}: {is_follower}")

        except Exception as e:
            logger.error(f"Error rechecking follow status: {str(e)}")

    def _resolve_branch_conditions(
        self, step: Dict[str, Any], account_id: str, postback_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve branch conditions and get the appropriate message.

        Branches can be conditional on is_follower, has_tag, etc.

        Args:
            step: Step configuration
            account_id: Account ID
            postback_data: Postback data

        Returns:
            Message to send or None
        """
        try:
            branches = step.get("branches", [])

            # Get contact for condition checking
            contact = self._get_contact(account_id, postback_data["contact_id"])

            if not contact:
                # Use default message if contact not found
                return step.get("message_template")

            # Check each branch condition
            for branch in branches:
                if self._check_branch_conditions(branch, contact):
                    return branch.get("message_template")

            # No conditions matched, use default
            return step.get("message_template")

        except Exception as e:
            logger.error(f"Error resolving branch conditions: {str(e)}")
            return step.get("message_template")

    def _get_contact(self, account_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
        """
        Get contact from database.

        Args:
            account_id: Account ID
            contact_id: Contact ID

        Returns:
            Contact data or None
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            return results[0] if results else None

        except Exception as e:
            logger.error(f"Error getting contact: {str(e)}")
            return None

    def _check_branch_conditions(
        self, branch: Dict[str, Any], contact: Dict[str, Any]
    ) -> bool:
        """
        Check if branch conditions are met for the contact.

        Args:
            branch: Branch configuration
            contact: Contact data

        Returns:
            True if conditions match
        """
        try:
            conditions = branch.get("conditions", [])

            if not conditions:
                return True

            condition_operator = branch.get("condition_operator", "AND")

            for condition in conditions:
                field = condition.get("field")
                value = condition.get("value")

                # Resolve field from contact data
                contact_value = contact.get(field)

                if condition_operator == "AND":
                    if contact_value != value:
                        return False
                else:  # OR
                    if contact_value == value:
                        return True

            return condition_operator == "AND"

        except Exception as e:
            logger.error(f"Error checking branch conditions: {str(e)}")
            return False

    def _send_message(
        self,
        account_id: str,
        contact_id: str,
        message: Dict[str, Any],
        automation: Dict[str, Any],
        step: Dict[str, Any],
        postback_data: Dict[str, Any],
    ) -> None:
        """
        Send the next message via Instagram API.

        Args:
            account_id: Account ID
            contact_id: Contact ID
            message: Message template
            automation: Automation configuration
            step: Step configuration
            postback_data: Postback data
        """
        try:
            from app.services.instagram_api import instagram_api
            from app.services.message_builder import message_builder

            # Build message
            context = {
                "automation_id": automation.get("id"),
                "step_id": step.get("id"),
                "contact_id": contact_id,
            }

            built_message = message_builder.build_message(message, context)

            if built_message:
                # Send message
                instagram_api.send_dm(account_id, contact_id, built_message)

                # Log delivery
                self._log_message_delivery(
                    account_id, contact_id, step.get("id"), built_message, "sent"
                )

        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")

    def _execute_on_deliver_actions(
        self, step: Dict[str, Any], account_id: str, contact_id: str
    ) -> None:
        """
        Execute on-deliver actions after message is sent.

        Actions: add_tag, enable_human_handoff, trigger_automation, schedule_message

        Args:
            step: Step configuration
            account_id: Account ID
            contact_id: Contact ID
        """
        try:
            on_deliver_actions = step.get("on_deliver_actions", [])

            for action in on_deliver_actions:
                logger.debug(f"Executing on-deliver action: {action.get('type')}")
                execute_on_deliver_action(action, account_id, contact_id)

        except Exception as e:
            logger.error(f"Error executing on-deliver actions: {str(e)}")

    def _track_button_click(
        self,
        account_id: str,
        postback_data: Dict[str, Any],
        automation: Dict[str, Any],
        step: Dict[str, Any],
    ) -> None:
        """
        Track button click analytics.

        Args:
            account_id: Account ID
            postback_data: Postback data
            automation: Automation configuration
            step: Step configuration
        """
        try:
            container = cosmos_db.get_container_client(self.message_logs_container)

            analytics_entry = {
                "id": f"click_{int(datetime.utcnow().timestamp())}_{postback_data['contact_id']}",
                "partition_key": "analytics",
                "account_id": account_id,
                "contact_id": postback_data["contact_id"],
                "automation_id": automation.get("id"),
                "step_id": step.get("id"),
                "event_type": "button_click",
                "button_title": postback_data.get("title"),
                "timestamp": postback_data.get("timestamp"),
            }

            container.create_item(analytics_entry)
            logger.debug(f"Tracked button click for {postback_data['contact_id']}")

        except Exception as e:
            logger.error(f"Error tracking button click: {str(e)}")

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
postback_processor = PostbackProcessor()


def process_postback_webhook(event: Dict[str, Any]) -> None:
    """
    Process postback webhook event.

    Args:
        event: Webhook event payload
    """
    postback_processor.process_postback_webhook(event)
