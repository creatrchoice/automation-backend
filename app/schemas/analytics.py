"""Analytics response schemas."""
from datetime import datetime, date
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class StepAnalyticsResponse(BaseModel):
    """Step analytics response."""

    step_id: str = Field(description="Step ID")
    step_name: str = Field(description="Step name")
    messages_sent: int = Field(description="Messages sent")
    messages_delivered: int = Field(description="Messages delivered")
    messages_failed: int = Field(description="Messages failed")
    messages_read: int = Field(description="Messages read")
    link_clicks: int = Field(description="Link clicks")
    postback_actions: int = Field(description="Postback actions")
    delivery_rate: float = Field(description="Delivery rate %")
    read_rate: float = Field(description="Read rate %")

    class Config:
        json_schema_extra = {
            "example": {
                "step_id": "step_1",
                "step_name": "Welcome",
                "messages_sent": 100,
                "messages_delivered": 98,
                "delivery_rate": 98.0,
                "read_rate": 75.0
            }
        }


class AutomationAnalyticsResponse(BaseModel):
    """Automation analytics response."""

    automation_id: str = Field(description="Automation ID")
    automation_name: str = Field(description="Automation name")
    times_triggered: int = Field(description="Times triggered")
    total_contacts_processed: int = Field(description="Contacts processed")
    total_messages_sent: int = Field(description="Messages sent")
    successful_completions: int = Field(description="Successful completions")
    completion_rate: float = Field(description="Completion rate %")
    delivery_rate: float = Field(description="Delivery rate %")
    read_rate: float = Field(description="Read rate %")
    click_through_rate: float = Field(description="Click-through rate %")
    reply_rate: float = Field(description="Reply rate %")
    steps: List[StepAnalyticsResponse] = Field(description="Per-step analytics")

    class Config:
        json_schema_extra = {
            "example": {
                "automation_id": "auto_123",
                "automation_name": "Welcome Sequence",
                "times_triggered": 50,
                "completion_rate": 90.0,
                "delivery_rate": 96.0,
                "read_rate": 75.0,
                "click_through_rate": 25.0,
                "steps": []
            }
        }


class DailyAnalyticsResponse(BaseModel):
    """Daily analytics response."""

    date: date = Field(description="Analytics date")
    account_id: str = Field(description="Account ID")
    total_messages_sent: int = Field(description="Total messages sent")
    total_messages_delivered: int = Field(description="Total delivered")
    total_messages_failed: int = Field(description="Total failed")
    total_messages_read: int = Field(description="Total read")
    total_contacts_messaged: int = Field(description="Unique contacts messaged")
    new_contacts_added: int = Field(description="New contacts added")
    delivery_rate: float = Field(description="Delivery rate %")
    read_rate: float = Field(description="Read rate %")
    failure_rate: float = Field(description="Failure rate %")
    response_rate: float = Field(description="Response rate %")
    automations_triggered: int = Field(description="Automations triggered")
    automations_completed: int = Field(description="Automations completed")
    automations: Dict[str, AutomationAnalyticsResponse] = Field(description="Per-automation breakdown")

    class Config:
        json_schema_extra = {
            "example": {
                "date": "2024-01-15",
                "account_id": "acc_123",
                "total_messages_sent": 500,
                "delivery_rate": 96.0,
                "read_rate": 75.0,
                "automations": {}
            }
        }


class DateRangeAnalyticsResponse(BaseModel):
    """Analytics for date range."""

    start_date: date = Field(description="Start date")
    end_date: date = Field(description="End date")
    account_id: str = Field(description="Account ID")
    total_messages_sent: int = Field(description="Total messages sent")
    total_messages_delivered: int = Field(description="Total delivered")
    total_messages_failed: int = Field(description="Total failed")
    total_messages_read: int = Field(description="Total read")
    total_contacts_messaged: int = Field(description="Unique contacts")
    new_contacts_added: int = Field(description="New contacts")
    delivery_rate: float = Field(description="Delivery rate %")
    read_rate: float = Field(description="Read rate %")
    failure_rate: float = Field(description="Failure rate %")
    response_rate: float = Field(description="Response rate %")
    avg_response_time_minutes: Optional[int] = Field(description="Avg response time")
    automations_triggered: int = Field(description="Automations triggered")
    automations_completed: int = Field(description="Automations completed")
    link_clicks: int = Field(description="Total link clicks")
    postback_actions: int = Field(description="Total postback actions")
    daily_breakdown: List[DailyAnalyticsResponse] = Field(description="Daily breakdown")

    class Config:
        json_schema_extra = {
            "example": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "account_id": "acc_123",
                "total_messages_sent": 15000,
                "delivery_rate": 96.5,
                "read_rate": 72.0,
                "daily_breakdown": []
            }
        }


class PerformanceMetricsResponse(BaseModel):
    """Performance metrics response."""

    period: str = Field(description="Period (hourly, daily, weekly)")
    account_id: str = Field(description="Account ID")
    average_send_latency_ms: float = Field(description="Avg send latency")
    p50_send_latency_ms: float = Field(description="Median send latency")
    p95_send_latency_ms: float = Field(description="95th percentile")
    p99_send_latency_ms: float = Field(description="99th percentile")
    average_delivery_latency_ms: float = Field(description="Avg delivery latency")
    average_read_latency_ms: Optional[float] = Field(description="Avg read latency")
    total_messages: int = Field(description="Total messages")
    failed_messages: int = Field(description="Failed messages")

    class Config:
        json_schema_extra = {
            "example": {
                "period": "daily",
                "account_id": "acc_123",
                "average_send_latency_ms": 245.5,
                "p95_send_latency_ms": 850.0,
                "average_delivery_latency_ms": 1200.5,
                "total_messages": 500
            }
        }


class EngagementMetricsResponse(BaseModel):
    """Engagement metrics."""

    period: str = Field(description="Period")
    account_id: str = Field(description="Account ID")
    total_messages_sent: int = Field(description="Messages sent")
    messages_read: int = Field(description="Messages read")
    read_rate: float = Field(description="Read rate %")
    total_link_clicks: int = Field(description="Link clicks")
    click_through_rate: float = Field(description="CTR %")
    total_postback_actions: int = Field(description="Postback actions")
    contacts_who_replied: int = Field(description="Contacts who replied")
    reply_rate: float = Field(description="Reply rate %")
    average_response_time_minutes: Optional[int] = Field(description="Avg response time")

    class Config:
        json_schema_extra = {
            "example": {
                "period": "daily",
                "account_id": "acc_123",
                "total_messages_sent": 500,
                "messages_read": 375,
                "read_rate": 75.0,
                "click_through_rate": 25.0,
                "reply_rate": 30.0
            }
        }


class ErrorBreakdownResponse(BaseModel):
    """Error breakdown."""

    opted_out: int = Field(description="Opted-out errors")
    window_expired: int = Field(description="Window expired errors")
    rate_limited: int = Field(description="Rate limit errors")
    suspended_account: int = Field(description="Suspended account errors")
    other_errors: int = Field(description="Other errors")
    total_errors: int = Field(description="Total errors")

    class Config:
        json_schema_extra = {
            "example": {
                "opted_out": 10,
                "window_expired": 5,
                "rate_limited": 2,
                "suspended_account": 1,
                "other_errors": 3,
                "total_errors": 21
            }
        }


class AnalyticsDashboardResponse(BaseModel):
    """Complete dashboard analytics."""

    account_id: str = Field(description="Account ID")
    period: str = Field(description="Period")
    daily_analytics: DailyAnalyticsResponse = Field(description="Daily analytics")
    performance_metrics: PerformanceMetricsResponse = Field(description="Performance metrics")
    engagement_metrics: EngagementMetricsResponse = Field(description="Engagement metrics")
    error_breakdown: ErrorBreakdownResponse = Field(description="Error breakdown")
    top_automations: List[AutomationAnalyticsResponse] = Field(description="Top automations")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123",
                "period": "daily",
                "daily_analytics": {},
                "performance_metrics": {},
                "engagement_metrics": {},
                "error_breakdown": {},
                "top_automations": []
            }
        }


class ExportAnalyticsRequest(BaseModel):
    """Export analytics request."""

    start_date: date = Field(description="Start date")
    end_date: date = Field(description="End date")
    format: str = Field(default="csv", description="Format (csv, xlsx, pdf)")
    include_daily: bool = Field(default=True, description="Include daily breakdown")
    include_automations: bool = Field(default=True, description="Include per-automation")
    include_steps: bool = Field(default=False, description="Include per-step data")

    class Config:
        json_schema_extra = {
            "example": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "format": "csv"
            }
        }
