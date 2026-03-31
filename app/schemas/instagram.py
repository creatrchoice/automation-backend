"""Instagram OAuth and account response schemas."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class InstagramOAuthCallbackRequest(BaseModel):
    """Instagram OAuth callback parameters."""

    code: str = Field(description="Authorization code from Instagram")
    state: str = Field(description="State parameter for CSRF protection")

    class Config:
        json_schema_extra = {
            "example": {
                "code": "abc123def456",
                "state": "secure_random_state_string"
            }
        }


class InstagramOAuthStartResponse(BaseModel):
    """Response with OAuth authorization URL."""

    authorization_url: str = Field(description="URL to redirect user to Instagram")
    state: str = Field(description="State parameter for this request")

    class Config:
        json_schema_extra = {
            "example": {
                "authorization_url": "https://instagram.com/oauth/authorize?client_id=...",
                "state": "secure_random_state_string"
            }
        }


class InstagramAccountResponse(BaseModel):
    """Instagram account information response."""

    id: str = Field(description="Account connection ID")
    ig_account_id: str = Field(description="Instagram account ID")
    ig_username: str = Field(description="Instagram username")
    ig_name: str = Field(description="Account display name")
    ig_biography: Optional[str] = Field(description="Account bio")
    ig_profile_pic_url: Optional[str] = Field(description="Profile picture URL")
    ig_followers_count: int = Field(description="Follower count")
    ig_media_count: int = Field(description="Post count")
    status: str = Field(description="Account status (active, inactive, suspended)")
    is_verified: bool = Field(description="Instagram verified badge")
    permissions: List[str] = Field(description="Granted permissions")
    connected_at: datetime = Field(description="When account was connected")
    last_verified_at: Optional[datetime] = Field(description="Last verification time")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "acc_123abc456",
                "ig_account_id": "17841401234567890",
                "ig_username": "mybusinessaccount",
                "ig_name": "My Business",
                "ig_followers_count": 50000,
                "status": "active",
                "is_verified": True,
                "permissions": ["instagram_basic", "instagram_graph_user_media"],
                "connected_at": "2024-01-01T00:00:00"
            }
        }


class InstagramAccountListResponse(BaseModel):
    """List of connected Instagram accounts."""

    accounts: List[InstagramAccountResponse] = Field(description="Connected accounts")
    total: int = Field(description="Total number of accounts")

    class Config:
        json_schema_extra = {
            "example": {
                "accounts": [],
                "total": 0
            }
        }


class SetPrimaryAccountRequest(BaseModel):
    """Set primary Instagram account."""

    account_id: str = Field(description="Account ID to set as primary")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123abc456"
            }
        }


class DisconnectAccountRequest(BaseModel):
    """Disconnect Instagram account."""

    account_id: str = Field(description="Account ID to disconnect")
    revoke_permissions: bool = Field(
        default=True,
        description="Revoke permissions from Instagram"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123abc456",
                "revoke_permissions": True
            }
        }


class RefreshAccountTokenRequest(BaseModel):
    """Refresh Instagram account token."""

    account_id: str = Field(description="Account ID")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123abc456"
            }
        }


class AccountStatusResponse(BaseModel):
    """Account status check response."""

    account_id: str = Field(description="Account ID")
    status: str = Field(description="Status (active, inactive, suspended, revoked)")
    is_connected: bool = Field(description="Account is properly connected")
    token_valid: bool = Field(description="Access token is valid")
    token_expires_at: Optional[datetime] = Field(description="Token expiration time")
    last_checked: datetime = Field(description="Last status check time")
    issues: List[str] = Field(default_factory=list, description="Any issues detected")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123abc456",
                "status": "active",
                "is_connected": True,
                "token_valid": True,
                "last_checked": "2024-01-15T10:30:00",
                "issues": []
            }
        }
