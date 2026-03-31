"""Raw webhook event storage for Instagram messages and statuses."""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import uuid


class WebhookEventType(str, Enum):
    """Types of webhook events from Instagram."""
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_STATUS = "message_status"
    MESSAGE_ECHO = "message_echo"
    DELIVERY_CONFIRMATION = "delivery_confirmation"
    READ_CONFIRMATION = "read_confirmation"
    MESSAGING_OPTINS = "messaging_optins"
    MESSAGING_OPTOUTS = "messaging_optouts"
    POSTBACK = "postback"
    REFERRAL = "referral"
    STANDBY = "standby"
    PASS_THREAD_CONTROL = "pass_thread_control"
    TAKE_THREAD_CONTROL = "take_thread_control"
    POLICY_ENFORCEMENT = "policy_enforcement"
    APP_ROLES = "app_roles"
    UNKNOWN = "unknown"


class MessageStatusType(str, Enum):
    """Message status types."""
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class WebhookEvent(BaseModel):
    """Raw webhook event from Instagram."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event ID")
    account_id: str = Field(description="Instagram account ID that received event")
    user_id: str = Field(description="Owner user ID")

    # Event metadata
    event_type: WebhookEventType = Field(description="Type of event")
    event_id: str = Field(description="Event ID from Instagram webhook")
    timestamp: int = Field(description="Unix timestamp from Instagram")

    # Sender and recipient
    sender_id: Optional[str] = Field(default=None, description="User ID who sent message/action")
    sender_username: Optional[str] = Field(default=None, description="Username of sender")
    recipient_id: Optional[str] = Field(default=None, description="Message recipient ID")

    # Message details
    message_id: Optional[str] = Field(default=None, description="Message ID")
    message_text: Optional[str] = Field(default=None, description="Message text content")
    message_mid: Optional[str] = Field(default=None, description="Message MID from Instagram")

    # Attachments
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Message attachments"
    )

    # Status information
    status_type: Optional[MessageStatusType] = Field(default=None, description="Message status type")
    is_echo: bool = Field(default=False, description="Is this an echo of our message")

    # Referral data
    referral_ref: Optional[str] = Field(default=None, description="Referral data")
    referral_ref_type: Optional[str] = Field(default=None, description="Referral type")

    # Postback data
    postback_payload: Optional[str] = Field(default=None, description="Postback action payload")
    postback_title: Optional[str] = Field(default=None, description="Postback button title")

    # Policy enforcement
    action: Optional[str] = Field(default=None, description="Policy enforcement action")
    reason: Optional[str] = Field(default=None, description="Reason for action")

    # Raw payload for debugging
    raw_payload: Dict[str, Any] = Field(
        description="Raw event payload from Instagram"
    )

    # Processing state
    processed: bool = Field(default=False, description="Event has been processed")
    processing_error: Optional[str] = Field(default=None, description="Error during processing")
    processed_at: Optional[datetime] = Field(default=None, description="When event was processed")

    # Linked entities
    contact_id: Optional[str] = Field(default=None, description="Linked contact ID")
    automation_id: Optional[str] = Field(default=None, description="Automation triggered by event")
    message_log_id: Optional[str] = Field(default=None, description="Linked message log ID")

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When event was received"
    )
    received_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when webhook was called"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "evt_123abc456",
                "account_id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "event_type": "message_received",
                "event_id": "evt_instagram_123",
                "timestamp": 1234567890,
                "sender_id": "123456789",
                "sender_username": "john.doe",
                "message_id": "mid_123",
                "message_text": "Hello!",
                "processed": False,
                "raw_payload": {}
            }
        }


class WebhookEventInDB(WebhookEvent):
    """Webhook event as stored in database."""

    partition_key: str = Field(default="webhook_event", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "evt_123abc456",
                "partition_key": "webhook_event",
                "account_id": "acc_123abc456"
            }
        }


class WebhookEventStats(BaseModel):
    """Statistics about webhook events."""

    account_id: str = Field(description="Account ID")
    period: str = Field(description="Time period")

    # Event counts by type
    total_events: int = Field(description="Total events received")
    messages_received: int = Field(default=0)
    status_updates: int = Field(default=0)
    delivery_confirmations: int = Field(default=0)
    read_confirmations: int = Field(default=0)
    postbacks: int = Field(default=0)
    optins: int = Field(default=0)
    optouts: int = Field(default=0)

    # Processing stats
    processed_events: int = Field(description="Successfully processed")
    failed_events: int = Field(description="Failed to process")
    pending_events: int = Field(description="Still pending")

    # Timestamps
    period_start: datetime = Field(description="Period start")
    period_end: datetime = Field(description="Period end")
