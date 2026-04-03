"""Webhook routes for receiving Instagram messages and events."""
import logging
import hmac
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.config import dm_settings
from app.core.errors import ForbiddenError, UnauthorizedError, BadRequestError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.get("/instagram")
async def verify_instagram_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """
    Handle Instagram webhook verification challenge.

    Meta sends a GET request to verify webhook endpoint ownership.
    We must respond with the hub.challenge value as a plain integer
    if the verify token matches.

    Query Parameters (sent by Meta):
        hub.mode: Should be "subscribe"
        hub.verify_token: Must match our WEBHOOK_VERIFY_TOKEN
        hub.challenge: Random integer to echo back

    Returns:
        PlainTextResponse: The hub.challenge value (as plain text integer)

    Status Codes:
        200: Verification successful
        403: Invalid token or mode
    """
    if hub_mode != "subscribe":
        logger.warning(f"Invalid hub_mode: {hub_mode}")
        raise ForbiddenError(
            message=f"Invalid hub.mode: {hub_mode}",
            user_message="Webhook verification failed: invalid mode.",
        )

    if hub_verify_token != dm_settings.WEBHOOK_VERIFY_TOKEN:
        logger.warning("Invalid verify token received")
        raise ForbiddenError(
            message="Invalid hub.verify_token",
            user_message="Webhook verification failed: invalid token.",
        )

    # CRITICAL: Return challenge as plain text, not JSON.
    logger.info("Webhook verification successful")
    return PlainTextResponse(content=hub_challenge, status_code=200)


@router.post("/instagram")
async def receive_instagram_webhook(request: Request):
    """
    Receive and process Instagram webhook events.

    Meta sends webhook events for:
    - Incoming direct messages
    - Message delivery/read status
    - Messaging postbacks (button clicks)
    - Story replies/reactions
    - Comment mentions

    The X-Hub-Signature-256 header contains an HMAC-SHA256 signature
    computed using the App Secret as the key and the raw request body
    as the message. Format: "sha256=<hex_digest>"

    Payload format:
    {
        "object": "instagram",
        "entry": [
            {
                "id": "<ig_user_id>",
                "time": <unix_timestamp>,
                "messaging": [
                    {
                        "sender": {"id": "<sender_ig_id>"},
                        "recipient": {"id": "<recipient_ig_id>"},
                        "timestamp": <unix_timestamp_ms>,
                        "message": {
                            "mid": "<message_id>",
                            "text": "Hello"
                        }
                    }
                ]
            }
        ]
    }

    Returns:
        dict: "EVENT_RECEIVED" acknowledgment (Meta best practice)

    Status Codes:
        200: Webhook received and queued for processing
        401: Invalid or missing signature
        400: Invalid payload
        500: Server error
    """
    try:
        # Step 1: Read raw body BEFORE any parsing (required for HMAC)
        body = await request.body()

        # Step 2: Validate X-Hub-Signature-256 header
        signature_header = request.headers.get("X-Hub-Signature-256", "")

        if not signature_header:
            logger.warning("Missing X-Hub-Signature-256 header")
            raise UnauthorizedError(message="Missing X-Hub-Signature-256 header")

        # Step 3: Parse signature header (format: "sha256=<hex_digest>")
        try:
            scheme, received_signature = signature_header.split("=", 1)
        except ValueError:
            logger.warning(f"Invalid signature header format: {signature_header}")
            raise UnauthorizedError(message="Invalid signature header format")

        if scheme != "sha256":
            logger.warning(f"Invalid signature scheme: {scheme}")
            raise UnauthorizedError(message=f"Invalid signature scheme: {scheme}")

        # Step 4: Compute expected HMAC-SHA256 using App Secret
        expected_signature = hmac.new(
            dm_settings.INSTAGRAM_APP_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        # Step 5: Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(received_signature, expected_signature):
            logger.warning("Webhook signature mismatch - possible tampering")
            raise UnauthorizedError(message="Webhook signature mismatch")

        # Step 6: Parse JSON payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload: {e}")
            raise BadRequestError(message=f"Invalid JSON payload: {e}")

        # Step 7: Validate it's an Instagram webhook
        if payload.get("object") != "instagram":
            logger.warning(f"Non-Instagram webhook object: {payload.get('object')}")
            raise BadRequestError(message=f"Invalid webhook object: {payload.get('object')}")

        # Step 8: Enqueue for async processing
        # IMPORTANT: Return 200 immediately. Meta expects response within 20 seconds.
        # If we don't respond in time, Meta will retry and may disable the webhook.
        await _enqueue_webhook_events(payload)

        # Meta best practice: return "EVENT_RECEIVED" with 200
        return {"status": "EVENT_RECEIVED"}

    except (UnauthorizedError, BadRequestError):
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        # Still return 200 to prevent Meta from retrying
        # Log the error for investigation
        return {"status": "EVENT_RECEIVED"}


async def _enqueue_webhook_events(payload: dict):
    """
    Enqueue webhook events for async processing.

    Extracts individual messaging events from the payload and either:
    1. Sends to Azure Service Bus (production) for worker processing
    2. Processes inline via Celery task (fallback)

    Args:
        payload: Full webhook payload from Meta
    """
    try:
        entries = payload.get("entry", [])

        for entry in entries:
            ig_account_id = entry.get("id")
            timestamp = entry.get("time")

            # Handle messaging events (DMs, postbacks, read receipts)
            messaging_events = entry.get("messaging", [])
            for event in messaging_events:
                event_envelope = {
                    "ig_account_id": ig_account_id,
                    "webhook_timestamp": timestamp,
                    "event": event,
                    "event_source": "messaging",
                }
                await _dispatch_event(event_envelope)

            # Handle changes events (comments, feed updates)
            changes = entry.get("changes", [])
            for change in changes:
                event_envelope = {
                    "ig_account_id": ig_account_id,
                    "webhook_timestamp": timestamp,
                    "event": change,
                    "event_source": "changes",
                    "field": change.get("field"),
                }
                await _dispatch_event(event_envelope)

    except Exception as e:
        logger.error(f"Error enqueuing webhook events: {e}", exc_info=True)
        # Don't raise - we already returned 200 to Meta


async def _dispatch_event(event_envelope: dict):
    """
    Dispatch a single event to the processing pipeline.

    Tries Azure Service Bus first, falls back to Celery task.

    Args:
        event_envelope: Wrapped event with metadata
    """
    try:
        # Option 1: Azure Service Bus (preferred for production)
        if dm_settings.AZURE_SERVICE_BUS_CONNECTION_STRING:
            from azure.servicebus.aio import ServiceBusClient
            from azure.servicebus import ServiceBusMessage

            async with ServiceBusClient.from_connection_string(
                dm_settings.AZURE_SERVICE_BUS_CONNECTION_STRING
            ) as client:
                sender = client.get_queue_sender(
                    queue_name=dm_settings.AZURE_SERVICE_BUS_QUEUE_NAME
                )
                async with sender:
                    message = ServiceBusMessage(
                        json.dumps(event_envelope),
                        session_id=event_envelope.get("ig_account_id", "default"),
                    )
                    await sender.send_messages(message)

            logger.debug(
                f"Event enqueued to Service Bus for account {event_envelope.get('ig_account_id')}"
            )
            return

        # Option 2: Celery task (fallback for dev / when Service Bus is not configured)
        try:
            from app.tasks.celery_app import celery_app

            celery_app.send_task(
                "app.tasks.process_webhook_event",
                args=[event_envelope],
                queue="webhooks",
            )
            logger.debug("Event dispatched to Celery webhook queue")
            return
        except Exception as celery_err:
            logger.warning(f"Celery dispatch failed: {celery_err}")

        # Option 3: Inline processing (last resort, for local dev)
        logger.warning("No async queue available - processing inline (not recommended for production)")
        from app.workers.webhook_processor import webhook_processor
        webhook_processor.process_webhook_synchronously(event_envelope)

    except Exception as e:
        logger.error(f"Failed to dispatch event: {e}", exc_info=True)
