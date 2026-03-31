"""Authentication request/response schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr = Field(description="User email")
    password: str = Field(description="User password", min_length=6)

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "securepassword123"
            }
        }


class SignupRequest(BaseModel):
    """User signup request."""

    email: EmailStr = Field(description="User email")
    name: str = Field(description="Full name", min_length=2)
    password: str = Field(description="Password", min_length=8)
    password_confirm: str = Field(description="Confirm password", min_length=8)

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "name": "John Doe",
                "password": "SecurePassword123!",
                "password_confirm": "SecurePassword123!"
            }
        }


class TokenRequest(BaseModel):
    """Request new access token."""

    refresh_token: str = Field(description="Refresh token")

    class Config:
        json_schema_extra = {
            "example": {
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }


class TokenResponse(BaseModel):
    """Token response with access and refresh tokens."""

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(description="Access token expiration in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }


class UserResponse(BaseModel):
    """User profile response."""

    id: str = Field(description="User ID")
    email: EmailStr = Field(description="Email")
    name: str = Field(description="Full name")
    subscription_tier: str = Field(description="Subscription tier")
    is_active: bool = Field(description="Account active")
    is_verified: bool = Field(description="Email verified")
    timezone: str = Field(description="Timezone")
    created_at: datetime = Field(description="Account creation time")
    last_login: Optional[datetime] = Field(description="Last login time")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "usr_123abc456",
                "email": "user@example.com",
                "name": "John Doe",
                "subscription_tier": "professional",
                "is_active": True,
                "is_verified": True,
                "timezone": "America/New_York",
                "created_at": "2024-01-01T00:00:00",
                "last_login": "2024-01-15T10:30:00"
            }
        }


class ChangePasswordRequest(BaseModel):
    """Change password request."""

    current_password: str = Field(description="Current password")
    new_password: str = Field(description="New password", min_length=8)
    new_password_confirm: str = Field(description="Confirm new password", min_length=8)


class ResetPasswordRequest(BaseModel):
    """Request password reset."""

    email: EmailStr = Field(description="Email address")


class ResetPasswordConfirm(BaseModel):
    """Confirm password reset with token."""

    token: str = Field(description="Reset token from email")
    new_password: str = Field(description="New password", min_length=8)
    new_password_confirm: str = Field(description="Confirm new password", min_length=8)


class VerifyEmailRequest(BaseModel):
    """Verify email with token."""

    token: str = Field(description="Verification token from email")


class EnableTwoFactorRequest(BaseModel):
    """Request to enable 2FA."""

    method: str = Field(default="totp", description="2FA method (totp, email, sms)")


class ConfirmTwoFactorRequest(BaseModel):
    """Confirm 2FA setup."""

    code: str = Field(description="2FA code from authenticator or email")


class APIKeyRequest(BaseModel):
    """Create API key."""

    name: str = Field(description="API key name", min_length=1)
    expires_in_days: Optional[int] = Field(default=None, description="Expiration in days")


class APIKeyResponse(BaseModel):
    """API key response."""

    id: str = Field(description="API key ID")
    key: str = Field(description="API key (shown only once)")
    name: str = Field(description="API key name")
    created_at: datetime = Field(description="Creation time")
    expires_at: Optional[datetime] = Field(description="Expiration time")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "key_123abc456",
                "key": "dm_sk_1234567890abcdef",
                "name": "Integration Key",
                "created_at": "2024-01-01T00:00:00"
            }
        }
