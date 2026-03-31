"""Message log with latency tracking."""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import uuid


class DeliveryStatus(str, Enum):
    """Message delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    SKIPPED = "skipped"
    BOUNCED = "bounced"


class FailureReason(str, Enum):
    """Reasons for message delivery failure."""
    RATE_LIMITED = "rate_limited"
    INVALID_RECIPIENT = "invalid_recipient"
    OPTED_OUT = "opted_out"
    MESSAGING_WINDOW_EXPIRED = "messaging_window_expired"
    ACCOUNT_SUSPENDED = "account_suspended"
    NETWORK_ERROR = "network_error"
    INSTAGRAM_ERROR = "instagram_error"
    TEMPLATE_ERROR = "template_error"
    UNKNOWN = "unknown"


class MessageLog(BaseModel):
    """Log entry for a sent message."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message log ID")
    account_id: str = Field(description="Instagram account ID")
    user_id: str = Field(description="Owner user ID")
    contact_id: str = Field(description="Recipient contact ID")

    # Message content
    message_text: str = Field(description="Message text content")
    message_template_id: Optional[str] = Field(default=None, description="Template used")

    # Automation context
    automation_id: Optional[str] = Field(default=None, description="Automation ID that sent message")
    step_id: Optional[str] = Field(default=None, description="Step ID in automation")

    # Delivery tracking
    status: DeliveryStatus = Field(default=DeliveryStatus.PENDING, description="Delivery status")
    instagram_message_id: Optional[str] = Field(default=None, description="ID from Instagram")

    # Failure information
    failure_reason: Optional[FailureReason] = Field(default=None, description="Reason for failure if failed")
    failure_details: Optional[str] = Field(default=None, description="Additional failure details")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    max_retries: int = Field(default=3, description="Max retry attempts")

    # Latency tracking (for performance monitoring)
    sent_at: Optional[datetime] = Field(default=None, description="When message was sent to Instagram")
    delivered_at: Optional[datetime] = Field(default=None, description="When Instagram confirmed delivery")
    read_at: Optional[datetime] = Field(default=None, description="When recipient read message")

    # Calculate latency in milliseconds
    send_latency_ms: Optional[int] = Field(default=None, description="Time to send to Instagram (ms)")
    delivery_latency_ms: Optional[int] = Field(default=None, description="Time from send to delivery (ms)")
    read_latency_ms: Optional[int] = Field(default=None, description="Time from send to read (ms)")

    # Request/response tracking
    request_id: Optional[str] = Field(default=None, description="API request ID for debugging")
    instagram_error_code: Optional[str] = Field(default=None, description="Instagram error code if failed")
    instagram_error_message: Optional[str] = Field(default=None, description="Instagram error message")

    # Engagement
    has_been_read: bool = Field(default=False, description="Message has been read")
    click_count: int = Field(default=0, description="Number of link clicks in message")
    postback_actions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Postback actions triggered from message"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When log entry was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "log_123abc456",
                "account_id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "contact_id": "con_123abc456",
                "message_text": "Hello John!",
                "automation_id": "auto_xyz",
                "step_id": "step_1",
                "status": "delivered",
                "instagram_message_id": "m123456",
                "send_latency_ms": 245,
                "delivery_latency_ms": 1200,
                "read_latency_ms": 35000,
                "has_been_read": True
            }
        }


class MessageLogInDB(MessageLog):
    """Message log as stored in database."""

    partition_key: str = Field(default="message_log", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "log_123abc456",
                "partition_key": "message_log",
                "account_id": "acc_123abc456"
            }
        }


class MessageLatencyMetrics(BaseModel):
    """Aggregated latency metrics for performance monitoring."""

    period: str = Field(description="Time period (hourly, daily, weekly)")
    account_id: str = Field(description="Account ID")
    automation_id: Optional[str] = Field(default=None, description="Automation ID if specific")

    # Latency statistics
    avg_send_latency_ms: float = Field(description="Average send latency")
    p50_send_latency_ms: float = Field(description="Median send latency")
    p95_send_latency_ms: float = Field(description="95th percentile send latency")
    p99_send_latency_ms: float = Field(description="99th percentile send latency")

    avg_delivery_latency_ms: float = Field(description="Average delivery latency")
    p50_delivery_latency_ms: float = Field(description="Median delivery latency")
    p95_delivery_latency_ms: float = Field(description="95th percentile delivery latency")

    avg_read_latency_ms: Optional[float] = Field(default=None, description="Average read latency")

    # Message statistics
    total_messages_sent: int = Field(description="Total messages sent")
    successful_deliveries: int = Field(description="Successfully delivered")
    delivery_rate: float = Field(description="Delivery rate percentage")
    read_rate: float = Field(description="Read rate percentage")
    failure_count: int = Field(description="Failed messages")

    # Error breakdown
    rate_limit_errors: int = Field(default=0)
    opted_out_errors: int = Field(default=0)
    window_expired_errors: int = Field(default=0)
    other_errors: int = Field(default=0)

    # Timestamps
    period_start: datetime = Field(description="Period start time")
    period_end: datetime = Field(description="Period end time")
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
