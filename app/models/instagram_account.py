"""Connected Instagram account model with encrypted tokens."""
from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid


class AccountStatus(str, Enum):
    """Instagram account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    PENDING_VERIFICATION = "pending_verification"


class InstagramAccount(BaseModel):
    """Connected Instagram business account with encrypted tokens."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique account ID")
    user_id: str = Field(description="Owner user ID")

    # Instagram Account Details
    ig_account_id: str = Field(description="Instagram business account ID (from IG API)")
    ig_username: str = Field(description="Instagram username")
    ig_name: str = Field(description="Account display name")
    ig_biography: Optional[str] = Field(default=None, description="Account bio")
    ig_profile_pic_url: Optional[str] = Field(default=None, description="Profile picture URL")
    ig_followers_count: int = Field(default=0, description="Current follower count")
    ig_media_count: int = Field(default=0, description="Total posts count")
    ig_category: Optional[str] = Field(default=None, description="Account category (creator, business, etc.)")

    # Authentication & Tokens
    access_token: str = Field(description="Encrypted Instagram access token")
    access_token_expires_at: Optional[datetime] = Field(
        default=None,
        description="Token expiration timestamp (long-lived tokens don't expire)"
    )
    refresh_token: Optional[str] = Field(
        default=None,
        description="Encrypted refresh token if available"
    )

    # Account Permissions
    permissions: List[str] = Field(
        default_factory=list,
        description="Granted permissions (instagram_basic, instagram_graph_user_media, etc.)"
    )

    # Account Status & Validation
    status: AccountStatus = Field(
        default=AccountStatus.ACTIVE,
        description="Current account status"
    )
    is_verified: bool = Field(default=False, description="Account is verified by Instagram")
    verification_code: Optional[str] = Field(default=None, description="Verification code if pending")

    # Rate Limiting
    api_calls_today: int = Field(default=0, description="API calls made today")
    api_call_limit: int = Field(default=200, description="Daily API call limit")
    last_api_call_reset: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last reset of daily API counter"
    )

    # Message Limits
    messages_sent_today: int = Field(default=0, description="Messages sent today")
    message_rate_limit_per_hour: int = Field(default=200, description="Messages per hour limit")
    last_message_rate_reset: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last reset of hourly message counter"
    )

    # Connected Automations
    active_automations: List[str] = Field(
        default_factory=list,
        description="List of active automation IDs using this account"
    )
    total_contacts: int = Field(default=0, description="Total contacts in database for this account")
    total_automations: int = Field(default=0, description="Total automations using this account")

    # Account Details from Insights (if available)
    last_insights_fetch: Optional[datetime] = Field(
        default=None,
        description="Last time insights were fetched"
    )

    # Webhook Configuration
    webhook_enabled: bool = Field(default=True, description="Webhook events are enabled")
    webhook_subscribed_events: List[str] = Field(
        default_factory=lambda: ["messages", "message_status"],
        description="Subscribed webhook event types"
    )

    # Connection Details
    connected_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When account was connected"
    )
    last_verified_at: Optional[datetime] = Field(
        default=None,
        description="Last successful API verification"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp"
    )

    # Metadata
    metadata: dict = Field(
        default_factory=dict,
        description="Custom metadata"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "acc_123abc456",
                "user_id": "usr_123abc456",
                "ig_account_id": "17841401234567890",
                "ig_username": "mybusinessaccount",
                "ig_name": "My Business",
                "access_token": "encrypted_token_string",
                "permissions": ["instagram_basic", "instagram_graph_user_media"],
                "status": "active",
                "is_verified": True,
                "api_calls_today": 45,
                "api_call_limit": 200,
                "messages_sent_today": 12,
                "message_rate_limit_per_hour": 200,
                "active_automations": ["auto_xyz"],
                "total_contacts": 5000
            }
        }


class InstagramAccountInDB(InstagramAccount):
    """Instagram account model as stored in database."""

    partition_key: str = Field(default="instagram_account", description="Partition key for Cosmos DB")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "acc_123abc456",
                "partition_key": "instagram_account",
                "user_id": "usr_123abc456",
                "ig_account_id": "17841401234567890",
                "ig_username": "mybusinessaccount"
            }
        }


class AccountTokenRefresh(BaseModel):
    """Model for token refresh data."""

    account_id: str = Field(description="Account ID to refresh")
    new_access_token: str = Field(description="New encrypted access token")
    expires_at: Optional[datetime] = Field(default=None, description="New expiration time")
    refreshed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When token was refreshed"
    )
