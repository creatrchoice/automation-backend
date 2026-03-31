"""DM Automation models."""
from app.models.user import (
    User,
    UserInDB,
    UserActivity,
    SubscriptionTier,
    BillingCycle,
)
from app.models.instagram_account import (
    InstagramAccount,
    InstagramAccountInDB,
    AccountTokenRefresh,
    AccountStatus,
)
from app.models.automation import (
    Automation,
    AutomationInDB,
    AutomationStep,
    AutomationTrigger,
    MessageTemplate,
    Button,
    CarouselElement,
    Condition,
    ConditionalBranch,
    FollowUpConfig,
    OnDeliverAction,
    AutomationStatus,
    TriggerType,
    MatchType,
    MessageType,
    ButtonType,
    DeliveryStatus,
)
from app.models.contact import (
    Contact,
    ContactInDB,
    ContactNote,
    Interaction,
    InteractionType,
)
from app.models.message_log import (
    MessageLog,
    MessageLogInDB,
    MessageLatencyMetrics,
    FailureReason,
)
from app.models.webhook_event import (
    WebhookEvent,
    WebhookEventInDB,
    WebhookEventStats,
    WebhookEventType,
    MessageStatusType,
)
from app.models.scheduled_task import (
    ScheduledTask,
    ScheduledTaskInDB,
    TaskExecutionLog,
    TaskType,
    TaskStatus,
    TaskPriority,
)
from app.models.analytics import (
    DailyAnalytics,
    DailyAnalyticsInDB,
    AutomationAnalytics,
    StepAnalytics,
    AnalyticsQuery,
)

__all__ = [
    # User models
    "User",
    "UserInDB",
    "UserActivity",
    "SubscriptionTier",
    "BillingCycle",
    # Instagram account models
    "InstagramAccount",
    "InstagramAccountInDB",
    "AccountTokenRefresh",
    "AccountStatus",
    # Automation models
    "Automation",
    "AutomationInDB",
    "AutomationStep",
    "AutomationTrigger",
    "MessageTemplate",
    "Button",
    "CarouselElement",
    "Condition",
    "ConditionalBranch",
    "FollowUpConfig",
    "OnDeliverAction",
    "AutomationStatus",
    "TriggerType",
    "MatchType",
    "MessageType",
    "ButtonType",
    "DeliveryStatus",
    # Contact models
    "Contact",
    "ContactInDB",
    "ContactNote",
    "Interaction",
    "InteractionType",
    # Message log models
    "MessageLog",
    "MessageLogInDB",
    "MessageLatencyMetrics",
    "FailureReason",
    # Webhook models
    "WebhookEvent",
    "WebhookEventInDB",
    "WebhookEventStats",
    "WebhookEventType",
    "MessageStatusType",
    # Scheduled task models
    "ScheduledTask",
    "ScheduledTaskInDB",
    "TaskExecutionLog",
    "TaskType",
    "TaskStatus",
    "TaskPriority",
    # Analytics models
    "DailyAnalytics",
    "DailyAnalyticsInDB",
    "AutomationAnalytics",
    "StepAnalytics",
    "AnalyticsQuery",
]
