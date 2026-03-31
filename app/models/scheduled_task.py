"""Follow-up and delayed task model."""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid


class TaskType(str, Enum):
    """Types of scheduled tasks."""
    SEND_MESSAGE = "send_message"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    SET_CUSTOM_FIELD = "set_custom_field"
    CREATE_NOTE = "create_note"
    FOLLOW_UP_MESSAGE = "follow_up_message"
    AUTOMATION_TRIGGER = "automation_trigger"
    CONTACT_CLEANUP = "contact_cleanup"


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class TaskPriority(str, Enum):
    """Task priority level."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ScheduledTask(BaseModel):
    """Scheduled task for follow-ups and delayed actions."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique task ID")
    account_id: str = Field(description="Instagram account ID")
    user_id: str = Field(description="Owner user ID")

    # Task details
    task_type: TaskType = Field(description="Type of task")
    task_name: str = Field(description="Human-readable task name")
    description: Optional[str] = Field(default=None, description="Task description")

    # Context
    contact_id: Optional[str] = Field(default=None, description="Contact this task is for")
    automation_id: Optional[str] = Field(default=None, description="Associated automation")
    step_id: Optional[str] = Field(default=None, description="Associated automation step")
    message_log_id: Optional[str] = Field(default=None, description="Original message this is follow-up for")

    # Task payload (varies by task_type)
    payload: Dict[str, Any] = Field(
        description="Task-specific payload"
    )

    # Scheduling
    scheduled_for: datetime = Field(description="When task should execute")
    timezone: str = Field(default="UTC", description="Timezone for scheduled_for")

    # Execution
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current status")
    priority: TaskPriority = Field(default=TaskPriority.NORMAL, description="Task priority")

    # Retry configuration
    retry_count: int = Field(default=0, description="Number of retry attempts")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    last_retry_at: Optional[datetime] = Field(default=None, description="Last retry time")
    next_retry_at: Optional[datetime] = Field(default=None, description="Next retry time")

    # Execution details
    executed_at: Optional[datetime] = Field(default=None, description="When task was executed")
    execution_error: Optional[str] = Field(default=None, description="Error if execution failed")
    execution_duration_ms: Optional[int] = Field(default=None, description="Execution time in ms")

    # Follow-up specific
    is_follow_up: bool = Field(default=False, description="Is this a follow-up message")
    original_message_id: Optional[str] = Field(default=None, description="Original message ID")
    follow_up_trigger: Optional[str] = Field(
        default=None,
        description="What triggered follow-up (NO_REPLY, NO_CLICK, CUSTOM)"
    )

    # Conditions for execution
    execute_if_condition: Optional[str] = Field(
        default=None,
        description="Condition that must be met to execute"
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When task was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "tsk_123abc456",
                "account_id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "task_type": "follow_up_message",
                "task_name": "Follow-up after 24 hours",
                "contact_id": "con_xyz",
                "automation_id": "auto_abc",
                "scheduled_for": "2024-01-15T10:30:00",
                "status": "scheduled",
                "payload": {"message_template_id": "tpl_123"},
                "is_follow_up": True,
                "follow_up_trigger": "NO_REPLY"
            }
        }


class ScheduledTaskInDB(ScheduledTask):
    """Scheduled task as stored in database."""

    partition_key: str = Field(default="scheduled_task", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "tsk_123abc456",
                "partition_key": "scheduled_task",
                "account_id": "acc_123abc456"
            }
        }


class TaskExecutionLog(BaseModel):
    """Log of task execution attempts."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Log ID")
    task_id: str = Field(description="Task ID")
    attempt_number: int = Field(description="Which attempt this is")

    # Execution details
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    duration_ms: int = Field(default=0)

    # Result
    success: bool = Field(description="Whether execution succeeded")
    error_message: Optional[str] = Field(default=None)
    error_code: Optional[str] = Field(default=None)

    # Output
    output: Dict[str, Any] = Field(default_factory=dict, description="Execution output")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
