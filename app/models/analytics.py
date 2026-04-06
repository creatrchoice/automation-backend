"""Daily analytics with per-automation, per-step breakdown."""
from datetime import datetime, date
from typing import Optional, Dict, List
from pydantic import BaseModel, Field
import uuid


class StepAnalytics(BaseModel):
    """Analytics for a single automation step."""

    step_id: str = Field(description="Step ID")
    step_name: str = Field(description="Step display name")

    # Message metrics
    messages_sent: int = Field(default=0, description="Messages sent from this step")
    messages_delivered: int = Field(default=0, description="Successfully delivered")
    messages_failed: int = Field(default=0, description="Failed deliveries")
    messages_read: int = Field(default=0, description="Messages read")

    # Engagement
    link_clicks: int = Field(default=0, description="Link clicks in messages")
    postback_actions: int = Field(default=0, description="Postback button clicks")
    average_response_time_minutes: Optional[int] = Field(default=None, description="Avg response time")

    # Branching
    branch_taken_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="How many times each branch was taken"
    )

    # Follow-ups
    follow_ups_sent: int = Field(default=0, description="Follow-up messages sent")
    follow_up_delivery_rate: float = Field(default=0.0, description="Follow-up delivery rate %")

    # Performance
    average_send_latency_ms: float = Field(default=0.0, description="Avg send time")
    average_delivery_latency_ms: float = Field(default=0.0, description="Avg delivery time")

    class Config:
        json_schema_extra = {
            "example": {
                "step_id": "step_1",
                "step_name": "Welcome Message",
                "messages_sent": 100,
                "messages_delivered": 98,
                "messages_failed": 2,
                "messages_read": 75,
                "link_clicks": 25,
                "postback_actions": 10
            }
        }


class AutomationAnalytics(BaseModel):
    """Analytics for a single automation."""

    automation_id: str = Field(description="Automation ID")
    automation_name: str = Field(description="Automation name")

    # Execution metrics
    times_triggered: int = Field(default=0, description="How many times triggered")
    total_contacts_processed: int = Field(default=0, description="Total unique contacts")
    total_messages_sent: int = Field(default=0, description="Total messages sent")

    # Success metrics
    successful_completions: int = Field(default=0, description="Automations completed successfully")
    completion_rate: float = Field(default=0.0, description="Completion rate %")
    avg_completion_time_hours: Optional[float] = Field(default=None, description="Avg time to complete")

    # Delivery metrics
    total_messages_delivered: int = Field(default=0, description="Delivered messages")
    delivery_rate: float = Field(default=0.0, description="Delivery rate %")
    total_messages_failed: int = Field(default=0, description="Failed messages")
    failure_rate: float = Field(default=0.0, description="Failure rate %")

    # Engagement
    total_messages_read: int = Field(default=0, description="Read messages")
    read_rate: float = Field(default=0.0, description="Read rate %")
    total_link_clicks: int = Field(default=0, description="Total link clicks")
    click_through_rate: float = Field(default=0.0, description="CTR %")
    total_postback_actions: int = Field(default=0, description="Postback button clicks")

    # Response metrics
    contacts_who_replied: int = Field(default=0, description="Contacts who replied")
    reply_rate: float = Field(default=0.0, description="Reply rate %")
    average_response_time_minutes: Optional[int] = Field(default=None, description="Avg response time")

    # Step breakdown
    step_analytics: Dict[str, StepAnalytics] = Field(
        default_factory=dict,
        description="Analytics per step"
    )

    # Error breakdown
    opt_out_errors: int = Field(default=0, description="Opted-out errors")
    window_expired_errors: int = Field(default=0, description="Messaging window expired")
    rate_limit_errors: int = Field(default=0, description="Rate limit errors")
    other_errors: int = Field(default=0, description="Other errors")

    # Performance
    average_send_latency_ms: float = Field(default=0.0, description="Avg send latency")
    average_delivery_latency_ms: float = Field(default=0.0, description="Avg delivery latency")

    class Config:
        json_schema_extra = {
            "example": {
                "automation_id": "auto_123",
                "automation_name": "Welcome Sequence",
                "times_triggered": 50,
                "total_contacts_processed": 50,
                "total_messages_sent": 100,
                "successful_completions": 45,
                "completion_rate": 90.0,
                "delivery_rate": 96.0,
                "read_rate": 75.0,
                "click_through_rate": 25.0
            }
        }


class DailyAnalytics(BaseModel):
    """Daily analytics aggregated by account."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Analytics ID")
    account_id: str = Field(description="Instagram account ID")
    user_id: str = Field(description="Owner user ID")

    # Date
    date: date = Field(description="Analytics date")

    # Account-level metrics
    total_messages_sent: int = Field(default=0, description="All messages sent")
    total_messages_delivered: int = Field(default=0, description="All delivered")
    total_messages_failed: int = Field(default=0, description="All failed")
    total_messages_read: int = Field(default=0, description="All read")

    # Engagement
    total_link_clicks: int = Field(default=0, description="All link clicks")
    total_postback_actions: int = Field(default=0, description="All postback clicks")
    total_contacts_messaged: int = Field(default=0, description="Unique contacts messaged")
    new_contacts_added: int = Field(default=0, description="New contacts in database")

    # Response metrics
    contacts_replied: int = Field(default=0, description="Contacts who replied")
    avg_response_time_minutes: Optional[int] = Field(default=None, description="Avg response time")

    # Automation metrics
    automations_triggered: int = Field(default=0, description="Times automations triggered")
    automations_completed: int = Field(default=0, description="Automations completed")

    # Rates
    delivery_rate: float = Field(default=0.0, description="Overall delivery rate %")
    read_rate: float = Field(default=0.0, description="Overall read rate %")
    failure_rate: float = Field(default=0.0, description="Overall failure rate %")
    response_rate: float = Field(default=0.0, description="Overall response rate %")

    # Rate limiting
    rate_limit_hits: int = Field(default=0, description="Times rate limited")
    api_call_count: int = Field(default=0, description="API calls made")

    # Error breakdown
    opted_out_count: int = Field(default=0, description="Opted-out rejections")
    window_expired_count: int = Field(default=0, description="Messaging window expired")
    suspended_account_count: int = Field(default=0, description="Suspended account rejections")
    other_errors_count: int = Field(default=0, description="Other errors")

    # Per-automation breakdown
    automations: Dict[str, AutomationAnalytics] = Field(
        default_factory=dict,
        description="Analytics per automation"
    )

    # Performance metrics
    average_send_latency_ms: float = Field(default=0.0, description="Avg send latency")
    average_delivery_latency_ms: float = Field(default=0.0, description="Avg delivery latency")
    p95_send_latency_ms: Optional[float] = Field(default=None, description="95th percentile send latency")
    p99_send_latency_ms: Optional[float] = Field(default=None, description="99th percentile send latency")

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When analytics were created"
    )
    calculated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When analytics were calculated"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "ana_123abc456",
                "account_id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "date": "2024-01-15",
                "total_messages_sent": 500,
                "total_messages_delivered": 480,
                "total_messages_failed": 20,
                "total_messages_read": 360,
                "total_contacts_messaged": 120,
                "delivery_rate": 96.0,
                "read_rate": 75.0,
                "failure_rate": 4.0,
                "automations_triggered": 5,
                "automations_completed": 4
            }
        }


class DailyAnalyticsInDB(DailyAnalytics):
    """Daily analytics as stored in database."""

    partition_key: str = Field(default="analytics", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "ana_123abc456",
                "account_id": "acc_123abc456",
                "date": "2024-01-15"
            }
        }


class AnalyticsQuery(BaseModel):
    """Query parameters for analytics."""

    start_date: date = Field(description="Start date (inclusive)")
    end_date: date = Field(description="End date (inclusive)")
    account_id: Optional[str] = Field(default=None, description="Filter by account")
    automation_id: Optional[str] = Field(default=None, description="Filter by automation")
    step_id: Optional[str] = Field(default=None, description="Filter by step")
    group_by: str = Field(default="daily", description="Group by (daily, weekly, monthly)")
