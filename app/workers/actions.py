"""On-deliver action executor for automation step completion."""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db
from app.db.redis import redis_client

logger = logging.getLogger(__name__)

# Deduplicate public comment replies (e.g. when webhook is processed inline + from queue)
_PUBLIC_COMMENT_REPLY_DEDUP_TTL_SECONDS = 6 * 3600


class ActionExecutor:
    """Execute on-deliver actions after messages are sent."""

    def __init__(self):
        """Initialize action executor."""
        self.contacts_container = dm_settings.DM_CONTACTS_CONTAINER
        self.scheduled_tasks_container = dm_settings.DM_SCHEDULED_TASKS_CONTAINER

    def execute_on_deliver_action(
        self,
        action: Dict[str, Any],
        account_id: str,
        contact_ig_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Execute an on-deliver action.

        Handles: add_tag, remove_tag, enable_human_handoff, trigger_automation,
        schedule_message, recheck_follow_status, reply_to_instagram_comment

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
            context: Optional webhook context (e.g. comment_id for public replies)
        """
        try:
            action_type = action.get("type")
            logger.debug(f"Executing action: {action_type} for contact {contact_ig_id}")

            if action_type == "add_tag":
                self.execute_add_tag(action, account_id, contact_ig_id)

            elif action_type == "remove_tag":
                self.execute_remove_tag(action, account_id, contact_ig_id)

            elif action_type == "enable_human_handoff":
                self.execute_enable_human_handoff(action, account_id, contact_ig_id)

            elif action_type == "trigger_automation":
                self.execute_trigger_automation(action, account_id, contact_ig_id)

            elif action_type == "schedule_message":
                self.execute_schedule_message(action, account_id, contact_ig_id)

            elif action_type == "recheck_follow_status":
                self.execute_recheck_follow_status(action, account_id, contact_ig_id)

            elif action_type == "reply_to_instagram_comment":
                self.execute_reply_to_instagram_comment(
                    action, account_id, contact_ig_id, context
                )

            else:
                logger.warning(f"Unknown action type: {action_type}")

        except Exception as e:
            logger.exception(f"Error executing on-deliver action: {str(e)}")

    def execute_add_tag(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Add tag to contact.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            tag = action.get("tag")

            if not tag:
                logger.warning("add_tag action missing 'tag' parameter")
                return

            container = cosmos_db.get_container_client(self.contacts_container)

            # Query contact
            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_ig_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                logger.warning(f"Contact {contact_ig_id} not found")
                return

            contact = results[0]
            tags = contact.get("tags", [])

            # Add tag if not already present
            if tag not in tags:
                tags.append(tag)
                contact["tags"] = tags
                contact["updated_at"] = datetime.utcnow().isoformat()

                container.replace_item(contact["id"], contact, partition_key=account_id)
                logger.info(f"Added tag '{tag}' to contact {contact_ig_id}")
            else:
                logger.debug(f"Contact {contact_ig_id} already has tag '{tag}'")

        except Exception as e:
            logger.error(f"Error adding tag: {str(e)}")

    def execute_remove_tag(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Remove tag from contact.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            tag = action.get("tag")

            if not tag:
                logger.warning("remove_tag action missing 'tag' parameter")
                return

            container = cosmos_db.get_container_client(self.contacts_container)

            # Query contact
            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_ig_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                logger.warning(f"Contact {contact_ig_id} not found")
                return

            contact = results[0]
            tags = contact.get("tags", [])

            # Remove tag if present
            if tag in tags:
                tags.remove(tag)
                contact["tags"] = tags
                contact["updated_at"] = datetime.utcnow().isoformat()

                container.replace_item(contact["id"], contact, partition_key=account_id)
                logger.info(f"Removed tag '{tag}' from contact {contact_ig_id}")
            else:
                logger.debug(f"Contact {contact_ig_id} doesn't have tag '{tag}'")

        except Exception as e:
            logger.error(f"Error removing tag: {str(e)}")

    def execute_enable_human_handoff(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Enable human handoff for conversation.

        Sets flag, stops automation, pushes WebSocket notification.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            container = cosmos_db.get_container_client(self.contacts_container)

            # Query contact
            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_ig_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if not results:
                logger.warning(f"Contact {contact_ig_id} not found")
                return

            contact = results[0]

            # Set handoff flags
            contact["human_handoff_active"] = True
            contact["human_handoff_at"] = datetime.utcnow().isoformat()
            contact["human_handoff_notes"] = action.get("notes", "Handed off to human agent")
            contact["updated_at"] = datetime.utcnow().isoformat()

            container.replace_item(contact["id"], contact, partition_key=account_id)
            logger.info(f"Enabled human handoff for contact {contact_ig_id}")

            # Push WebSocket notification
            self._send_websocket_notification(
                account_id,
                contact_ig_id,
                "human_handoff",
                {"reason": action.get("notes")},
            )

        except Exception as e:
            logger.error(f"Error enabling human handoff: {str(e)}")

    def execute_trigger_automation(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Trigger another automation via Celery delayed task.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            automation_id = action.get("automation_id")
            delay_seconds = action.get("delay_seconds", 0)

            if not automation_id:
                logger.warning("trigger_automation action missing 'automation_id'")
                return

            # Import here to avoid circular dependencies
            from app.tasks.celery_app import celery_app

            # Queue automation trigger task with delay
            if delay_seconds > 0:
                celery_app.send_task(
                    "trigger_automation",
                    args=[account_id, contact_ig_id, automation_id],
                    countdown=delay_seconds,
                )
                logger.info(
                    f"Queued automation {automation_id} "
                    f"for contact {contact_ig_id} with {delay_seconds}s delay"
                )
            else:
                celery_app.send_task(
                    "trigger_automation",
                    args=[account_id, contact_ig_id, automation_id],
                )
                logger.info(
                    f"Queued automation {automation_id} for contact {contact_ig_id}"
                )

        except Exception as e:
            logger.error(f"Error triggering automation: {str(e)}")

    def execute_schedule_message(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Create a scheduled message task.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            delay_minutes = action.get("delay_minutes")
            message_template = action.get("message_template")

            if not delay_minutes or not message_template:
                logger.warning(
                    "schedule_message action missing 'delay_minutes' or 'message_template'"
                )
                return

            container = cosmos_db.get_container_client(self.scheduled_tasks_container)

            # Calculate scheduled time
            scheduled_at = datetime.utcnow() + timedelta(minutes=delay_minutes)

            scheduled_task = {
                "id": f"sched_{int(datetime.utcnow().timestamp())}_{contact_ig_id}",
                "account_id": account_id,
                "contact_id": contact_ig_id,
                "message_template": message_template,
                "status": "pending",
                "scheduled_at": scheduled_at.isoformat(),
                "created_at": datetime.utcnow().isoformat(),
                "retry_count": 0,
                "max_retries": 3,
            }

            container.create_item(scheduled_task)
            logger.info(
                f"Scheduled message for contact {contact_ig_id} "
                f"at {scheduled_at.isoformat()}"
            )

        except Exception as e:
            logger.error(f"Error scheduling message: {str(e)}")

    def execute_recheck_follow_status(
        self, action: Dict[str, Any], account_id: str, contact_ig_id: str
    ) -> None:
        """
        Recheck and update contact's follow status.

        Args:
            action: Action configuration
            account_id: Account ID
            contact_ig_id: Contact Instagram ID
        """
        try:
            from app.services.instagram_api import instagram_api

            # Check follow status via Instagram API
            is_follower = instagram_api.check_follow_status(account_id, contact_ig_id)

            # Update contact
            container = cosmos_db.get_container_client(self.contacts_container)

            query = "SELECT c.* FROM c WHERE c.id = @id AND c.account_id = @account_id LIMIT 1"
            results = list(
                container.query_items(
                    query=query,
                    parameters=[
                        {"name": "@id", "value": contact_ig_id},
                        {"name": "@account_id", "value": account_id},
                    ],
                )
            )

            if results:
                contact = results[0]
                contact["custom_fields"] = contact.get("custom_fields", {})
                contact["custom_fields"]["is_follower"] = is_follower
                contact["updated_at"] = datetime.utcnow().isoformat()

                container.replace_item(contact["id"], contact, partition_key=account_id)
                logger.info(
                    f"Updated follow status for contact {contact_ig_id}: {is_follower}"
                )

        except Exception as e:
            logger.error(f"Error rechecking follow status: {str(e)}")

    def execute_reply_to_instagram_comment(
        self,
        action: Dict[str, Any],
        account_id: str,
        contact_ig_id: str,
        context: Optional[Dict[str, Any]],
    ) -> None:
        """
        Post a public reply to the user's comment (after a successful private DM).
        Requires context['comment_id'] from comment webhooks.
        """
        if action.get("only_if_send_succeeded") is False:
            # Call sites only invoke after a successful send; keep flag for future use
            pass

        if not context or not context.get("comment_id"):
            logger.warning(
                "reply_to_instagram_comment: missing context.comment_id; skipping"
            )
            return

        text = (action.get("message") or "").strip()
        if not text:
            logger.warning("reply_to_instagram_comment: missing 'message' in action")
            return

        comment_id = str(context["comment_id"])
        dedup_key = f"ig:public_comment_reply:{comment_id}"

        try:
            was_set = redis_client.set(
                dedup_key,
                "1",
                ex=_PUBLIC_COMMENT_REPLY_DEDUP_TTL_SECONDS,
                nx=True,
            )
            # redis-py: True if set, None/False if key already existed
            if not was_set:
                logger.info(
                    "Skipping duplicate public comment reply (already sent) for %s",
                    comment_id,
                )
                return
        except Exception as redis_err:
            logger.warning(
                "Redis idempotency unavailable for public reply (%s): %s; proceeding",
                comment_id,
                redis_err,
            )

        try:
            from app.services.instagram_api import instagram_api

            instagram_api.reply_to_instagram_comment_sync(
                account_id, comment_id, text
            )
        except Exception as e:
            logger.error(
                "Failed public comment reply for comment_id=%s: %s",
                comment_id,
                e,
            )

    def _send_websocket_notification(
        self,
        account_id: str,
        contact_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """
        Send WebSocket notification for real-time updates.

        Args:
            account_id: Account ID
            contact_id: Contact ID
            event_type: Type of event
            payload: Event payload
        """
        try:
            # This integrates with WebSocket handler
            notification = {
                "event_type": event_type,
                "account_id": account_id,
                "contact_id": contact_id,
                "payload": payload,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Queue notification to WebSocket
            notification_key = f"ws:notification:{account_id}"
            redis_client.publish(notification_key, str(notification))

            logger.debug(f"WebSocket notification sent: {event_type}")

        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {str(e)}")


# Global executor instance
action_executor = ActionExecutor()


def execute_on_deliver_action(
    action: Dict[str, Any],
    account_id: str,
    contact_ig_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Execute an on-deliver action.

    Args:
        action: Action configuration
        account_id: Account ID
        contact_ig_id: Contact Instagram ID
        context: Optional event context (e.g. comment_id)
    """
    action_executor.execute_on_deliver_action(
        action, account_id, contact_ig_id, context
    )
