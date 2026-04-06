"""Main webhook event processor and dispatcher."""
import logging
import json
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from app.core.config import dm_settings
from app.workers.comment_processor import process_comment_webhook
from app.workers.message_processor import process_message_webhook
from app.workers.postback_processor import process_postback_webhook
from app.db.cosmos_db import cosmos_db
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class WebhookEventType(str, Enum):
    """Instagram webhook event types."""
    COMMENT = "comment"
    MESSAGE = "message"
    POSTBACK = "postback"
    STORY = "story"
    FEED = "feed"
    UNKNOWN = "unknown"


class WebhookProcessor:
    """Main webhook processor for routing events to appropriate handlers."""

    def __init__(self):
        """Initialize webhook processor."""
        self.service_bus_client: Optional[ServiceBusClient] = None
        self.queue_receiver = None
        self.container_name = dm_settings.DM_WEBHOOK_EVENTS_CONTAINER

    def initialize_service_bus(self) -> None:
        """Initialize Azure Service Bus connection."""
        try:
            self.service_bus_client = ServiceBusClient.from_connection_string(
                dm_settings.AZURE_SERVICE_BUS_CONNECTION_STRING
            )
            self.queue_receiver = self.service_bus_client.get_queue_receiver(
                queue_name=dm_settings.AZURE_SERVICE_BUS_QUEUE_NAME,
                max_wait_time=30
            )
            logger.info("Service Bus initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Service Bus: {str(e)}")
            raise

    def close_service_bus(self) -> None:
        """Close Service Bus connection."""
        if self.service_bus_client:
            self.service_bus_client.close()

    def process_webhook_event(self, event: Dict[str, Any]) -> None:
        """
        Process a webhook event and route to appropriate handler.

        Args:
            event: Webhook event payload from Instagram
        """
        try:
            event_type = self._determine_event_type(event)
            webhook_id = event.get("id", "unknown")

            logger.info(f"Processing webhook event: {webhook_id} of type: {event_type}")

            # Deduplicate events within 24-hour window
            if self._is_duplicate_event(webhook_id):
                logger.warning(f"Duplicate event detected: {webhook_id}, skipping")
                return

            # Store webhook event for audit trail
            self._store_webhook_event(event, event_type)

            # Route to appropriate processor
            if event_type == WebhookEventType.COMMENT:
                process_comment_webhook(event)
            elif event_type == WebhookEventType.MESSAGE:
                process_message_webhook(event)
            elif event_type == WebhookEventType.POSTBACK:
                process_postback_webhook(event)
            elif event_type == WebhookEventType.STORY:
                # Story events use message processor with special handling
                process_message_webhook(event)
            else:
                logger.warning(f"Unknown webhook event type: {event_type}")

        except Exception as e:
            logger.exception(f"Error processing webhook event: {str(e)}")
            self._store_failed_webhook_event(event, str(e))
            raise

    def _determine_event_type(self, event: Dict[str, Any]) -> WebhookEventType:
        """
        Determine the type of webhook event based on payload structure.

        Args:
            event: Webhook event payload

        Returns:
            WebhookEventType enum value
        """
        # Check for comment events
        if "comments" in event or "text" in event and "message" not in event:
            return WebhookEventType.COMMENT

        # Check for message events
        if "message" in event:
            message = event.get("message", {})
            # Check if it's a story reply
            if message.get("reply_to", {}).get("story"):
                return WebhookEventType.STORY
            return WebhookEventType.MESSAGE

        # Check for postback events
        if "postback" in event:
            return WebhookEventType.POSTBACK

        # Check for feed/image events
        if "feed" in event or "media" in event:
            return WebhookEventType.FEED

        return WebhookEventType.UNKNOWN

    def _is_duplicate_event(self, event_id: str) -> bool:
        """
        Check if event has been processed recently (deduplication).

        Args:
            event_id: Webhook event ID

        Returns:
            True if duplicate, False otherwise
        """
        dedup_key = f"webhook:dedup:{event_id}"
        if redis_client.exists(dedup_key):
            return True

        # Mark as processed
        ttl_seconds = dm_settings.DEDUP_TTL_HOURS * 3600
        redis_client.setex(dedup_key, ttl_seconds, "1")
        return False

    def _store_webhook_event(
        self, event: Dict[str, Any], event_type: WebhookEventType
    ) -> None:
        """
        Store webhook event in Cosmos DB for audit trail.

        Args:
            event: Webhook event payload
            event_type: Type of webhook event
        """
        try:
            container = cosmos_db.get_container_client(self.container_name)

            # Extract account_id (partition key) from event envelope or recipient
            account_id = (
                event.get("ig_account_id")
                or event.get("recipient", {}).get("id")
                or "unknown"
            )

            webhook_record = {
                "id": event.get("id", f"webhook_{int(datetime.utcnow().timestamp())}"),
                "account_id": account_id,
                "event_type": event_type.value,
                "payload": event,
                "processed_at": datetime.utcnow().isoformat(),
                "status": "processed",
            }

            container.create_item(webhook_record)
            logger.debug(f"Stored webhook event: {webhook_record['id']}")
        except Exception as e:
            logger.error(f"Failed to store webhook event: {str(e)}")

    def _store_failed_webhook_event(self, event: Dict[str, Any], error: str) -> None:
        """
        Store failed webhook event for debugging.

        Args:
            event: Webhook event payload
            error: Error message
        """
        try:
            container = cosmos_db.get_container_client(self.container_name)

            # Extract account_id (partition key) from event envelope or recipient
            account_id = (
                event.get("ig_account_id")
                or event.get("recipient", {}).get("id")
                or "unknown"
            )

            webhook_record = {
                "id": f"webhook_failed_{int(datetime.utcnow().timestamp())}",
                "account_id": account_id,
                "event_type": "unknown",
                "payload": event,
                "error": error,
                "processed_at": datetime.utcnow().isoformat(),
                "status": "failed",
            }

            container.create_item(webhook_record)
        except Exception as e:
            logger.error(f"Failed to store failed webhook event: {str(e)}")

    def start_message_loop(self) -> None:
        """
        Start the Service Bus message consumption loop.

        This method runs indefinitely, processing messages from the queue.
        Should be run in a separate process/thread.
        """
        if not self.service_bus_client:
            self.initialize_service_bus()

        logger.info("Starting webhook message processing loop")

        try:
            while True:
                messages = self.queue_receiver.receive_messages(
                    max_message_count=10, max_wait_time=30
                )

                for message in messages:
                    try:
                        # Parse message body
                        event_data = json.loads(str(message))

                        # Process the event
                        self.process_webhook_event(event_data)

                        # Mark message as processed
                        self.queue_receiver.complete_message(message)
                        logger.debug(f"Completed message: {message.message_id}")

                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse message JSON: {str(e)}")
                        self.queue_receiver.complete_message(message)

                    except Exception as e:
                        logger.error(
                            f"Error processing message {message.message_id}: {str(e)}"
                        )
                        # Requeue message for retry
                        self.queue_receiver.renew_message_lock(message)

        except Exception as e:
            logger.exception(f"Error in message processing loop: {str(e)}")
            raise
        finally:
            self.close_service_bus()

    def process_webhook_synchronously(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a webhook event synchronously (for testing or immediate processing).

        Args:
            event: Webhook event payload

        Returns:
            Processing result
        """
        try:
            self.process_webhook_event(event)
            return {"status": "success", "event_id": event.get("id")}
        except Exception as e:
            logger.error(f"Synchronous webhook processing failed: {str(e)}")
            return {"status": "error", "error": str(e)}


# Global processor instance
webhook_processor = WebhookProcessor()
