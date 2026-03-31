"""Automation request/response schemas."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ButtonSchema(BaseModel):
    """Button schema for templates."""

    title: str = Field(description="Button text")
    type: str = Field(description="Button type (web_url, postback)")
    url: Optional[str] = Field(default=None, description="URL for web_url buttons")
    payload_action: Optional[str] = Field(default=None, description="Action for postback")
    payload_next_step: Optional[str] = Field(default=None, description="Next step for postback")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Button metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Learn More",
                "type": "web_url",
                "url": "https://example.com"
            }
        }


class CarouselElementSchema(BaseModel):
    """Carousel element schema."""

    title: str = Field(description="Element title")
    subtitle: Optional[str] = Field(default=None, description="Element subtitle")
    image_url: Optional[str] = Field(default=None, description="Image URL")
    buttons: List[ButtonSchema] = Field(default_factory=list, description="Buttons")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Product 1",
                "subtitle": "Great product",
                "image_url": "https://example.com/image.jpg",
                "buttons": []
            }
        }


class MessageTemplateSchema(BaseModel):
    """Message template schema."""

    message_type: str = Field(description="Type (text, generic_template, carousel)")
    text: Optional[str] = Field(default=None, description="Message text")
    generic_title: Optional[str] = Field(default=None, description="Generic template title")
    generic_subtitle: Optional[str] = Field(default=None, description="Generic template subtitle")
    generic_image_url: Optional[str] = Field(default=None, description="Generic template image")
    generic_buttons: List[ButtonSchema] = Field(default_factory=list, description="Generic template buttons")
    carousel_elements: List[CarouselElementSchema] = Field(
        default_factory=list,
        description="Carousel elements"
    )
    media_url: Optional[str] = Field(default=None, description="Media URL for image/video")
    media_caption: Optional[str] = Field(default=None, description="Media caption")

    class Config:
        json_schema_extra = {
            "example": {
                "message_type": "text",
                "text": "Hello {{first_name}}!"
            }
        }


class ConditionSchema(BaseModel):
    """Condition schema."""

    field: str = Field(description="Field to check")
    match_type: str = Field(description="Match type (equals, contains, etc.)")
    value: Any = Field(description="Value to match")
    case_sensitive: bool = Field(default=False, description="Case sensitive")

    class Config:
        json_schema_extra = {
            "example": {
                "field": "message_text",
                "match_type": "contains",
                "value": "help"
            }
        }


class ConditionalBranchSchema(BaseModel):
    """Conditional branch schema."""

    name: str = Field(description="Branch name")
    conditions: List[ConditionSchema] = Field(description="Conditions")
    condition_operator: str = Field(default="AND", description="AND or OR")
    next_step_id: Optional[str] = Field(default=None, description="Next step ID")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "If interested",
                "conditions": [],
                "next_step_id": "step_2"
            }
        }


class OnDeliverActionSchema(BaseModel):
    """On-deliver action schema."""

    action_type: str = Field(description="Action type (add_tag, set_field, etc.)")
    value: Any = Field(description="Action value")

    class Config:
        json_schema_extra = {
            "example": {
                "action_type": "add_tag",
                "value": "engaged"
            }
        }


class FollowUpConfigSchema(BaseModel):
    """Follow-up configuration."""

    enabled: bool = Field(default=False, description="Follow-up enabled")
    delay_minutes: int = Field(default=60, description="Minutes to wait")
    message_template_id: Optional[str] = Field(default=None, description="Follow-up template")
    condition_type: str = Field(default="NO_REPLY", description="Trigger condition")
    max_retries: int = Field(default=1, description="Max retries")

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "delay_minutes": 60,
                "condition_type": "NO_REPLY"
            }
        }


class StepSchema(BaseModel):
    """Automation step schema."""

    step_id: str = Field(description="Step ID")
    name: str = Field(description="Step name")
    order: int = Field(description="Order")
    message_template_id: str = Field(description="Template ID")
    branches: List[ConditionalBranchSchema] = Field(default_factory=list, description="Branches")
    default_next_step_id: Optional[str] = Field(default=None, description="Default next step")
    on_deliver_actions: List[OnDeliverActionSchema] = Field(
        default_factory=list,
        description="On-deliver actions"
    )
    follow_up_config: Optional[FollowUpConfigSchema] = Field(default=None, description="Follow-up")
    delay_before_send_minutes: int = Field(default=0, description="Delay before send")

    class Config:
        json_schema_extra = {
            "example": {
                "step_id": "step_1",
                "name": "Welcome",
                "order": 1,
                "message_template_id": "tpl_123"
            }
        }


class TriggerSchema(BaseModel):
    """Automation trigger schema."""

    trigger_type: str = Field(description="Trigger type")
    keywords: List[str] = Field(default_factory=list, description="Keywords")
    match_type: str = Field(default="contains", description="Match type")
    tags: List[str] = Field(default_factory=list, description="Tags")
    cron_expression: Optional[str] = Field(default=None, description="Cron expression")
    enabled: bool = Field(default=True, description="Enabled")

    class Config:
        json_schema_extra = {
            "example": {
                "trigger_type": "keyword_match",
                "keywords": ["help", "support"],
                "match_type": "contains"
            }
        }


class CreateAutomationRequest(BaseModel):
    """Create automation request."""

    name: str = Field(description="Automation name")
    description: Optional[str] = Field(default=None, description="Description")
    account_id: str = Field(description="Instagram account ID")
    trigger: TriggerSchema = Field(description="Trigger configuration")
    steps: List[StepSchema] = Field(description="Automation steps")
    start_step_id: str = Field(description="First step ID")
    daily_cap: Optional[int] = Field(default=None, description="Daily message cap")
    total_cap: Optional[int] = Field(default=None, description="Total message cap")
    tags: List[str] = Field(default_factory=list, description="Tags")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Welcome Sequence",
                "account_id": "acc_123",
                "trigger": {},
                "steps": [],
                "start_step_id": "step_1"
            }
        }


class UpdateAutomationRequest(BaseModel):
    """Update automation request."""

    name: Optional[str] = Field(default=None, description="Automation name")
    description: Optional[str] = Field(default=None, description="Description")
    trigger: Optional[TriggerSchema] = Field(default=None, description="Trigger")
    steps: Optional[List[StepSchema]] = Field(default=None, description="Steps")
    start_step_id: Optional[str] = Field(default=None, description="Start step")
    status: Optional[str] = Field(default=None, description="Status")
    daily_cap: Optional[int] = Field(default=None, description="Daily cap")
    total_cap: Optional[int] = Field(default=None, description="Total cap")
    tags: Optional[List[str]] = Field(default=None, description="Tags")


class AutomationResponse(BaseModel):
    """Automation response."""

    id: str = Field(description="Automation ID")
    user_id: str = Field(description="User ID")
    account_id: str = Field(description="Account ID")
    name: str = Field(description="Name")
    description: Optional[str] = Field(default=None)
    status: str = Field(description="Status")
    trigger: TriggerSchema = Field(description="Trigger")
    steps: List[StepSchema] = Field(description="Steps")
    start_step_id: str = Field(description="Start step ID")
    total_messages_sent: int = Field(description="Total messages sent")
    messages_sent: int = Field(description="Messages sent this period")
    created_at: datetime = Field(description="Created at")
    updated_at: datetime = Field(description="Updated at")
    last_run_at: Optional[datetime] = Field(default=None, description="Last run")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "auto_123",
                "user_id": "usr_456",
                "account_id": "acc_789",
                "name": "Welcome Sequence",
                "status": "active",
                "total_messages_sent": 100
            }
        }


class AutomationListResponse(BaseModel):
    """List of automations."""

    automations: List[AutomationResponse] = Field(description="Automations")
    total: int = Field(description="Total count")
    page: int = Field(description="Current page")
    page_size: int = Field(description="Page size")

    class Config:
        json_schema_extra = {
            "example": {
                "automations": [],
                "total": 0,
                "page": 1,
                "page_size": 25
            }
        }


class TestAutomationRequest(BaseModel):
    """Test automation with sample contact."""

    contact_id: str = Field(description="Contact ID to test with")
    start_step_id: str = Field(description="Step to start from")

    class Config:
        json_schema_extra = {
            "example": {
                "contact_id": "con_123",
                "start_step_id": "step_1"
            }
        }


class TestAutomationResponse(BaseModel):
    """Test automation result."""

    success: bool = Field(description="Test succeeded")
    message: str = Field(description="Result message")
    steps_executed: List[str] = Field(default_factory=list, description="Steps that executed")
    messages_that_would_send: List[str] = Field(
        default_factory=list,
        description="Messages that would be sent"
    )
    errors: List[str] = Field(default_factory=list, description="Any errors")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Automation test completed successfully",
                "steps_executed": ["step_1", "step_2"],
                "messages_that_would_send": ["Welcome message", "Follow-up message"]
            }
        }
