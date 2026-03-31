"""User account model with subscription tiers."""
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr
import uuid


class SubscriptionTier(str, Enum):
    """User subscription tier levels."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class BillingCycle(str, Enum):
    """Billing cycle frequency."""
    MONTHLY = "monthly"
    ANNUAL = "annual"


class User(BaseModel):
    """User account model for DM automation platform."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique user ID")
    email: EmailStr = Field(description="User email address")
    name: str = Field(description="User full name")
    password_hash: str = Field(description="Hashed password (bcrypt)")

    # Subscription
    subscription_tier: SubscriptionTier = Field(
        default=SubscriptionTier.FREE,
        description="Current subscription tier"
    )
    subscription_status: str = Field(
        default="active",
        description="Subscription status (active, paused, cancelled)"
    )
    billing_cycle: BillingCycle = Field(
        default=BillingCycle.MONTHLY,
        description="Billing cycle frequency"
    )
    subscription_start_date: Optional[datetime] = Field(
        default=None,
        description="When subscription started"
    )
    subscription_end_date: Optional[datetime] = Field(
        default=None,
        description="When subscription ends"
    )

    # Limits based on tier
    max_automations: int = Field(
        default=5,
        description="Maximum automations allowed"
    )
    max_contacts: int = Field(
        default=10000,
        description="Maximum contacts in database"
    )
    max_monthly_dms: int = Field(
        default=10000,
        description="Maximum DMs per month"
    )
    messages_sent_this_month: int = Field(
        default=0,
        description="Count of messages sent this month"
    )

    # Account management
    is_active: bool = Field(default=True, description="Account is active")
    is_verified: bool = Field(default=False, description="Email is verified")
    two_factor_enabled: bool = Field(default=False, description="2FA is enabled")

    # Preferences
    timezone: str = Field(default="UTC", description="User timezone")
    language: str = Field(default="en", description="Preferred language")
    notification_email_enabled: bool = Field(default=True, description="Email notifications enabled")

    # Connected accounts
    connected_ig_accounts: List[str] = Field(
        default_factory=list,
        description="List of connected Instagram account IDs"
    )
    primary_ig_account: Optional[str] = Field(
        default=None,
        description="Primary Instagram account ID for default operations"
    )

    # API keys
    api_keys: List[str] = Field(
        default_factory=list,
        description="Active API keys for this user"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Account creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )
    last_login: Optional[datetime] = Field(
        default=None,
        description="Last login timestamp"
    )

    # Metadata
    metadata: dict = Field(
        default_factory=dict,
        description="Custom metadata (e.g., company, industry, use_case)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "usr_123abc456",
                "email": "user@example.com",
                "name": "John Doe",
                "subscription_tier": "professional",
                "max_automations": 50,
                "max_contacts": 100000,
                "max_monthly_dms": 100000,
                "is_active": True,
                "timezone": "America/New_York"
            }
        }


class UserInDB(User):
    """User model as stored in database (includes password hash)."""

    partition_key: str = Field(default="user", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "usr_123abc456",
                "partition_key": "user",
                "email": "user@example.com",
                "name": "John Doe",
                "password_hash": "$2b$12$...",
                "subscription_tier": "professional"
            }
        }


class UserActivity(BaseModel):
    """Track user activity for analytics."""

    user_id: str = Field(description="User ID")
    activity_type: str = Field(description="Type of activity (login, automation_run, etc.)")
    metadata: dict = Field(default_factory=dict, description="Activity metadata")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Activity timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "usr_123abc456",
                "activity_type": "automation_run",
                "metadata": {"automation_id": "auto_xyz", "contact_count": 100}
            }
        }
