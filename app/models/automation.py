"""Automation model with steps, triggers, conditions, message templates, postback chains."""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class AutomationStatus(str, Enum):
    """Automation execution status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    DISABLED = "disabled"


class TriggerType(str, Enum):
    """Trigger types for automation."""
    MESSAGE_RECEIVED = "message_received"
    KEYWORD_MATCH = "keyword_match"
    TAG_ADDED = "tag_added"
    CUSTOM_FIELD_CHANGED = "custom_field_changed"
    MANUAL_TRIGGER = "manual_trigger"
    SCHEDULED = "scheduled"
    USER_ACTION = "user_action"


class MatchType(str, Enum):
    """Condition matching types."""
    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"
    IN_LIST = "in_list"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    BETWEEN = "between"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"


class MessageType(str, Enum):
    """Types of messages in templates."""
    TEXT = "text"
    GENERIC_TEMPLATE = "generic_template"
    CAROUSEL = "carousel"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"


class ButtonType(str, Enum):
    """Button action types."""
    WEB_URL = "web_url"
    POSTBACK = "postback"
    PHONE_NUMBER = "phone_number"
    EMAIL = "email"


class DeliveryStatus(str, Enum):
    """Message delivery status."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    SKIPPED = "skipped"
    BOUNCED = "bounced"


class TaskType(str, Enum):
    """Scheduled task types."""
    SEND_MESSAGE = "send_message"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    SET_CUSTOM_FIELD = "set_custom_field"
    CREATE_NOTE = "create_note"


class Condition(BaseModel):
    """Single condition in a rule."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Condition ID")
    field: str = Field(description="Field to check (e.g., 'message_text', 'tag', 'custom_field_x')")
    match_type: MatchType = Field(description="Type of matching to perform")
    value: Any = Field(description="Value to match against")
    case_sensitive: bool = Field(default=False, description="Case-sensitive matching")


class ConditionalBranch(BaseModel):
    """Branch in step execution based on conditions."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Branch ID")
    name: str = Field(description="Branch name for display")
    conditions: List[Condition] = Field(description="Conditions to evaluate")
    condition_operator: str = Field(
        default="AND",
        description="How to combine conditions (AND, OR)"
    )
    next_step_id: Optional[str] = Field(
        default=None,
        description="Next step ID if conditions match, None to end automation"
    )


class Button(BaseModel):
    """Button in message template."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Button ID")
    type: ButtonType = Field(description="Button type")
    title: str = Field(description="Button display text")
    url: Optional[str] = Field(default=None, description="URL for web_url buttons")
    payload_action: Optional[str] = Field(
        default=None,
        description="Action to perform (for postback)"
    )
    payload_next_step: Optional[str] = Field(
        default=None,
        description="Next step ID if button clicked (for postback)"
    )
    payload_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to pass with action"
    )


class CarouselElement(BaseModel):
    """Single element in carousel template."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Element ID")
    title: str = Field(description="Element title")
    subtitle: Optional[str] = Field(default=None, description="Element subtitle")
    image_url: Optional[str] = Field(default=None, description="Image URL")
    default_action_url: Optional[str] = Field(default=None, description="URL for default tap action")
    buttons: List[Button] = Field(default_factory=list, description="Buttons in this element")


class MessageTemplate(BaseModel):
    """Message template for automation steps."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Template ID")
    message_type: MessageType = Field(description="Type of message")

    # Text message
    text: Optional[str] = Field(default=None, description="Message text")

    # Generic template
    generic_title: Optional[str] = Field(default=None, description="Title for generic template")
    generic_subtitle: Optional[str] = Field(default=None, description="Subtitle for generic template")
    generic_image_url: Optional[str] = Field(default=None, description="Image URL for generic template")
    generic_buttons: List[Button] = Field(default_factory=list, description="Buttons for generic template")

    # Carousel
    carousel_elements: List[CarouselElement] = Field(default_factory=list, description="Elements in carousel")

    # Media
    media_url: Optional[str] = Field(default=None, description="URL for image/video/file")
    media_caption: Optional[str] = Field(default=None, description="Caption for media")

    # Variables for personalization ({{first_name}}, {{tag}}, etc.)
    variables_used: List[str] = Field(default_factory=list, description="Variables used in template")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FollowUpConfig(BaseModel):
    """Configuration for follow-up messages."""

    enabled: bool = Field(default=False, description="Follow-up is enabled")
    delay_minutes: int = Field(default=0, description="Minutes to wait before follow-up")
    message_template_id: Optional[str] = Field(default=None, description="Template for follow-up message")
    condition_type: str = Field(
        default="NO_REPLY",
        description="When to trigger (NO_REPLY, NO_CLICK, ALWAYS)"
    )
    max_retries: int = Field(default=1, description="Max follow-up retries")


class OnDeliverAction(BaseModel):
    """Actions to perform when message is delivered."""

    action_type: TaskType = Field(description="Action type")
    value: Any = Field(description="Action value (tag name, field value, etc.)")
    condition: Optional[str] = Field(default=None, description="Condition to trigger action")


class AutomationStep(BaseModel):
    """Single step in automation chain."""

    step_id: str = Field(description="Unique step identifier within automation")
    name: str = Field(description="Step display name")
    order: int = Field(description="Execution order")

    # Message
    message_template_id: str = Field(description="Message template ID")

    # Branching
    branches: List[ConditionalBranch] = Field(
        default_factory=list,
        description="Conditional branches from this step"
    )
    default_next_step_id: Optional[str] = Field(
        default=None,
        description="Default next step if no branch matches"
    )

    # Actions on delivery
    on_deliver_actions: List[OnDeliverAction] = Field(
        default_factory=list,
        description=(
            "Actions when message is delivered. At runtime, Cosmos may store "
            "flexible dicts with a `type` field, including `reply_to_instagram_comment` "
            "for a public comment reply (after DM) when comment_id is in context."
        ),
    )

    # Follow-up configuration
    follow_up_config: Optional[FollowUpConfig] = Field(
        default=None,
        description="Follow-up message configuration"
    )

    # Step conditions (when this step can execute)
    step_conditions: List[Condition] = Field(
        default_factory=list,
        description="Conditions for step to execute"
    )

    # Skip logic
    skip_if_conditions_not_met: bool = Field(
        default=False,
        description="Skip step if conditions not met (vs ending automation)"
    )

    # Delay
    delay_before_send_minutes: int = Field(default=0, description="Delay before sending")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AutomationTrigger(BaseModel):
    """Trigger that starts an automation."""

    trigger_type: TriggerType = Field(description="Type of trigger")

    # For MESSAGE_RECEIVED and KEYWORD_MATCH
    keywords: List[str] = Field(default_factory=list, description="Keywords to match")
    match_type: MatchType = Field(default=MatchType.CONTAINS, description="How to match keywords")

    # For TAG_ADDED
    tags: List[str] = Field(default_factory=list, description="Tags that trigger automation")

    # For CUSTOM_FIELD_CHANGED
    custom_field_name: Optional[str] = Field(default=None, description="Custom field name")
    custom_field_value: Optional[str] = Field(default=None, description="Custom field value")

    # For SCHEDULED
    cron_expression: Optional[str] = Field(default=None, description="Cron expression for scheduling")

    # General
    enabled: bool = Field(default=True, description="Trigger is enabled")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Automation(BaseModel):
    """Complete automation with all configuration."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique automation ID")
    user_id: str = Field(description="Owner user ID")
    account_id: str = Field(description="Instagram account ID using this automation")

    # Basic info
    name: str = Field(description="Automation name")
    description: Optional[str] = Field(default=None, description="Automation description")

    # Status
    status: AutomationStatus = Field(default=AutomationStatus.DRAFT, description="Automation status")

    # Trigger
    trigger: AutomationTrigger = Field(description="What triggers this automation")

    # Steps and flow
    steps: Dict[str, AutomationStep] = Field(
        description="Steps keyed by step_id"
    )
    start_step_id: str = Field(description="ID of first step to execute")

    # Targeting
    target_audience: Optional[str] = Field(default=None, description="Audience filter (tag, field, etc.)")

    # Limits
    daily_cap: Optional[int] = Field(default=None, description="Max messages per day")
    total_cap: Optional[int] = Field(default=None, description="Max total messages")
    messages_sent: int = Field(default=0, description="Messages sent by this automation")

    # Opt-out handling
    respect_opted_out: bool = Field(default=True, description="Skip opted-out contacts")
    check_messaging_window: bool = Field(default=True, description="Check 24-hour messaging window")

    # Metadata
    tags: List[str] = Field(default_factory=list, description="Tags for organizing automations")

    # Statistics
    total_contacts_processed: int = Field(default=0, description="Total contacts processed")
    total_messages_sent: int = Field(default=0, description="Total messages sent")
    failure_count: int = Field(default=0, description="Number of failures")

    # Scheduling
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )
    last_run_at: Optional[datetime] = Field(default=None, description="Last execution timestamp")
    next_run_at: Optional[datetime] = Field(default=None, description="Next scheduled execution")

    # Metadata
    metadata: dict = Field(default_factory=dict, description="Custom metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "auto_123abc456",
                "user_id": "usr_123abc456",
                "account_id": "acc_123abc456",
                "name": "Welcome Sequence",
                "status": "active",
                "trigger": {
                    "trigger_type": "tag_added",
                    "tags": ["lead"]
                },
                "steps": {},
                "start_step_id": "step_1"
            }
        }


class AutomationInDB(Automation):
    """Automation as stored in database."""

    partition_key: str = Field(default="automation", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "auto_123abc456",
                "user_id": "usr_123abc456"
            }
        }
