"""Contact model with tags, interaction history."""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class InteractionType(str, Enum):
    """Types of interactions with contact."""
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_READ = "message_read"
    LINK_CLICKED = "link_clicked"
    POSTBACK_ACTION = "postback_action"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
    NOTE_ADDED = "note_added"
    AUTOMATION_TRIGGERED = "automation_triggered"
    MANUAL_ACTION = "manual_action"


class Interaction(BaseModel):
    """Single interaction record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Interaction ID")
    interaction_type: InteractionType = Field(description="Type of interaction")
    message_id: Optional[str] = Field(default=None, description="Associated message ID")
    automation_id: Optional[str] = Field(default=None, description="Associated automation ID")
    step_id: Optional[str] = Field(default=None, description="Associated step ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Interaction metadata")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Interaction timestamp"
    )


class Contact(BaseModel):
    """Contact model with history and metadata."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique contact ID")
    account_id: str = Field(description="Instagram account ID")
    user_id: str = Field(description="Owner user ID")

    # Instagram details
    ig_id: str = Field(description="Instagram user/page ID")
    ig_username: str = Field(description="Instagram username")
    ig_name: Optional[str] = Field(default=None, description="Display name")
    ig_profile_pic: Optional[str] = Field(default=None, description="Profile picture URL")

    # Contact info
    email: Optional[str] = Field(default=None, description="Email address if available")
    phone: Optional[str] = Field(default=None, description="Phone number if available")

    # Tags for organization
    tags: List[str] = Field(
        default_factory=list,
        description="Tags assigned to contact"
    )

    # Custom fields
    custom_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom field values"
    )

    # Messaging state
    messaging_window_expires: Optional[datetime] = Field(
        default=None,
        description="When 24-hour messaging window expires"
    )
    opted_out: bool = Field(default=False, description="Contact opted out of messaging")
    opted_out_at: Optional[datetime] = Field(default=None, description="When contact opted out")
    opted_out_reason: Optional[str] = Field(default=None, description="Reason for opt-out")

    # Human handoff
    human_handoff_active: bool = Field(default=False, description="Conversation handed to human")
    human_handoff_at: Optional[datetime] = Field(default=None, description="When handed off")
    human_handoff_notes: Optional[str] = Field(default=None, description="Handoff notes")

    # Interaction tracking
    total_messages_sent: int = Field(default=0, description="Total messages sent to contact")
    total_messages_received: int = Field(default=0, description="Total messages received from contact")
    last_message_sent_at: Optional[datetime] = Field(default=None, description="Last outgoing message")
    last_message_received_at: Optional[datetime] = Field(default=None, description="Last incoming message")
    last_interaction_at: Optional[datetime] = Field(
        default=None,
        description="Last interaction of any type"
    )

    # Automation tracking
    automation_count: int = Field(default=0, description="Number of automations triggered")
    last_automation_triggered: Optional[str] = Field(default=None, description="Last automation ID triggered")
    last_automation_triggered_at: Optional[datetime] = Field(default=None, description="When last triggered")

    # Engagement metrics
    message_open_rate: float = Field(default=0.0, description="Percentage of messages opened")
    link_click_rate: float = Field(default=0.0, description="Percentage of links clicked")
    response_rate: float = Field(default=0.0, description="Response rate")
    average_response_time_minutes: int = Field(default=0, description="Avg response time in minutes")

    # Notes
    notes: str = Field(default="", description="Internal notes about contact")

    # Interaction history (last 100)
    interactions: List[Interaction] = Field(
        default_factory=list,
        description="Recent interactions"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom metadata"
    )

    # Timestamps
    first_contacted_at: Optional[datetime] = Field(default=None, description="First contact timestamp")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When contact was added"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "con_123abc456",
                "account_id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "ig_id": "123456789",
                "ig_username": "john.doe",
                "ig_name": "John Doe",
                "tags": ["lead", "vip"],
                "custom_fields": {"source": "instagram_search", "industry": "tech"},
                "opted_out": False,
                "total_messages_sent": 5,
                "total_messages_received": 2
            }
        }


class ContactInDB(Contact):
    """Contact as stored in database."""

    partition_key: str = Field(default="contact", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "con_123abc456",
                "partition_key": "contact",
                "account_id": "acc_123abc456"
            }
        }


class ContactNote(BaseModel):
    """Note added to a contact."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Note ID")
    contact_id: str = Field(description="Contact ID")
    user_id: str = Field(description="User who added note")
    content: str = Field(description="Note content")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Note creation timestamp"
    )
