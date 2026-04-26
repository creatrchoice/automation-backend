"""Main webhook event processor and dispatcher."""
import logging
import json
import time
import hashlib
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from app.core.config import dm_settings
from app.workers.comment_processor import process_comment_webhook
from app.workers.message_processor import process_message_webhook
from app.workers.postback_processor import process_postback_webhook
from app.db.cosmos_db import cosmos_db
from app.db.cosmos_containers import CONTAINER_WEBHOOK_EVENTS

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
        self.container_name = CONTAINER_WEBHOOK_EVENTS

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
        event_type = None
        webhook_id = "unknown"
        try:
            event_type = self._determine_event_type(event)
            webhook_id = self._event_dedup_id(event)

            logger.info(f"Processing webhook event: {webhook_id} of type: {event_type}")

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
            logger.exception(
                "Webhook processing failed webhook_id=%s event_type=%s ig_account_id=%s",
                webhook_id,
                event_type,
                event.get("ig_account_id"),
            )
            self._store_failed_webhook_event(event, str(e))
            raise

    def _determine_event_type(self, event: Dict[str, Any]) -> WebhookEventType:
        """
        Determine the type of webhook event based on payload structure.

        The event_envelope has this shape:
            {
                "ig_account_id": "...",
                "webhook_timestamp": ...,
                "event": { ... },          # The actual event payload
                "event_source": "messaging" | "changes",
                "field": "comments" | ...  # Only present for changes events
            }

        For messaging events, event["event"] contains sender/recipient/message.
        For changes events, event["event"] contains {"field": "comments", "value": {...}}.

        Args:
            event: Webhook event envelope

        Returns:
            WebhookEventType enum value
        """
        event_source = event.get("event_source")
        inner_event = event.get("event", {})

        # --- Changes-based events (comments, mentions, feed) ---
        if event_source == "changes":
            field = event.get("field") or inner_event.get("field", "")
            if field == "comments":
                return WebhookEventType.COMMENT
            if field in ("feed", "story_insights"):
                return WebhookEventType.FEED
            # Fallback: unknown changes field
            logger.warning(f"Unknown changes field: {field}")
            return WebhookEventType.UNKNOWN

        # --- Messaging-based events (DMs, postbacks, story replies) ---
        if event_source == "messaging":
            # Check for postback events
            if "postback" in inner_event:
                return WebhookEventType.POSTBACK

            # Check for message events
            if "message" in inner_event:
                message = inner_event.get("message", {})
                # Check if it's a story reply
                if message.get("reply_to", {}).get("story"):
                    return WebhookEventType.STORY
                return WebhookEventType.MESSAGE

            # Read receipts, delivery confirmations, etc.
            if "read" in inner_event or "delivery" in inner_event:
                return WebhookEventType.MESSAGE

            return WebhookEventType.UNKNOWN

        # --- Fallback for legacy/direct calls ---
        if "message" in event:
            return WebhookEventType.MESSAGE
        if "postback" in event:
            return WebhookEventType.POSTBACK

        return WebhookEventType.UNKNOWN

    def _event_dedup_id(self, event: Dict[str, Any]) -> str:
        """
        Build a stable dedup identifier for events without a provider event id.

        If upstream sends no id (common for changes/comment events), use a hash of
        normalized payload so replaying the same event does not trigger duplicate sends.
        """
        event_id = str(event.get("id") or "").strip()
        if event_id and event_id != "unknown":
            return event_id

        try:
            normalized = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            normalized = str(event)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        return f"hash_{digest}"

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

            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    container.create_item(webhook_record)
                    logger.debug(f"Stored webhook event: {webhook_record['id']}")
                    return
                except OSError as os_err:
                    if attempt == max_attempts:
                        raise
                    logger.warning(
                        "Transient OS error storing webhook event %s (attempt %s/%s): %s",
                        webhook_record["id"],
                        attempt,
                        max_attempts,
                        os_err,
                    )
                    time.sleep(0.5 * attempt)
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
        logger.info("Starting webhook message processing loop")

        while True:
            try:
                if not self.service_bus_client:
                    self.initialize_service_bus()

                messages = self.queue_receiver.receive_messages(
                    max_message_count=10, max_wait_time=30
                )

                for message in messages:
                    try:
                        # Parse message body from Service Bus message sections.
                        raw_body = b"".join(
                            part if isinstance(part, (bytes, bytearray)) else bytes(part)
                            for part in message.body
                        )
                        event_data = json.loads(raw_body.decode("utf-8"))

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
                logger.exception(
                    "Error in message processing loop: %s. Retrying in 5 seconds.",
                    str(e),
                )
                self.close_service_bus()
                self.service_bus_client = None
                self.queue_receiver = None
                time.sleep(5)

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
            logger.exception("Synchronous webhook processing failed: %s", e)
            return {"status": "error", "error": str(e)}


# Global processor instance
webhook_processor = WebhookProcessor()
