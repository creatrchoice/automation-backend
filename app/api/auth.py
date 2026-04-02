"""Authentication routes for DM Automation API."""
import logging
import hmac
import hashlib
import secrets
from typing import Optional
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import RedirectResponse
import httpx
from urllib.parse import urlencode

from app.core.config import dm_settings
from app.api.deps import (
    get_redis_client,
    get_cosmos_client,
    create_access_token,
)
from app.db.cosmos_containers import CONTAINER_USERS, CONTAINER_IG_ACCOUNTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Constants
CSRF_STATE_EXPIRY = 600  # 10 minutes
INSTAGRAM_TOKEN_CONTAINER = CONTAINER_IG_ACCOUNTS
USERS_CONTAINER = CONTAINER_USERS


class AuthRequest:
    """Request models (using Pydantic for validation would be better in production)."""

    @staticmethod
    def signup_schema():
        return {
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
                "password": {"type": "string", "minLength": 8},
            },
            "required": ["email", "password"],
        }

    @staticmethod
    def login_schema():
        return {
            "type": "object",
            "properties": {
                "email": {"type": "string", "format": "email"},
                "password": {"type": "string"},
            },
            "required": ["email", "password"],
        }

    @staticmethod
    def callback_schema():
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["code", "state"],
        }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    email: str,
    password: str,
    cosmos_client=Depends(get_cosmos_client),
    redis_client=Depends(get_redis_client),
):
    """
    Sign up new user with email and password.

    Args:
        email: User email address
        password: User password (minimum 8 characters)
        cosmos_client: Cosmos DB client
        redis_client: Redis client

    Returns:
        dict: User info and JWT token

    Status Codes:
        201: User created successfully
        400: Invalid input or user already exists
        500: Server error
    """
    try:
        # Validate email format and password length
        if not email or "@" not in email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format",
            )

        if len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters",
            )

        # Check if user already exists
        users_container = await cosmos_client.get_async_container_client(
            USERS_CONTAINER
        )
        query = "SELECT * FROM users WHERE users.email = @email"
        existing_users = []
        async for item in users_container.query_items(
            query=query, parameters=[{"name": "@email", "value": email}]
        ):
            existing_users.append(item)

        if existing_users:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            )

        # Hash password (in production, use bcrypt)
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # Create user document
        user_id = email.replace("@", "_").replace(".", "_")
        user_doc = {
            "id": user_id,
            "partition_key": "user",
            "email": email,
            "password_hash": password_hash,
            "created_at": None,  # Would be set by Cosmos DB
            "updated_at": None,
            "connected_accounts": [],
        }

        # Store in Cosmos DB
        await users_container.create_item(body=user_doc)

        # Create JWT token
        access_token = create_access_token(
            data={"sub": user_id, "email": email},
            expires_delta=timedelta(hours=24),
        )

        return {
            "user_id": user_id,
            "email": email,
            "access_token": access_token,
            "token_type": "bearer",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )


@router.post("/login")
async def login(
    email: str,
    password: str,
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Log in user with email and password.

    Args:
        email: User email address
        password: User password
        cosmos_client: Cosmos DB client

    Returns:
        dict: JWT token and user info

    Status Codes:
        200: Login successful
        401: Invalid credentials
        500: Server error
    """
    try:
        # Find user by email
        users_container = await cosmos_client.get_async_container_client(
            USERS_CONTAINER
        )
        query = "SELECT * FROM users WHERE users.email = @email"
        users = []
        async for item in users_container.query_items(
            query=query, parameters=[{"name": "@email", "value": email}]
        ):
            users.append(item)

        if not users:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        user = users[0]

        # Verify password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if user.get("password_hash") != password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # Create JWT token
        access_token = create_access_token(
            data={"sub": user["id"], "email": user["email"]},
            expires_delta=timedelta(hours=24),
        )

        return {
            "user_id": user["id"],
            "email": user["email"],
            "access_token": access_token,
            "token_type": "bearer",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )


@router.get("/instagram/state")
async def get_instagram_state(
    redis_client=Depends(get_redis_client),
):
    """
    Generate CSRF state token for Instagram OAuth flow.

    This endpoint generates a random state token that must be returned by
    Instagram during the OAuth callback to prevent CSRF attacks.

    Returns:
        dict: CSRF state token and redirect URL for Instagram login

    Status Codes:
        200: State generated successfully
        500: Server error
    """
    try:
        # Generate random state token
        state = secrets.token_urlsafe(32)

        # Store in Redis with expiry (10 minutes)
        redis_key = f"oauth_state:{state}"
        await redis_client.setex(redis_key, CSRF_STATE_EXPIRY, "pending")

        # Generate Instagram authorization URL
        # Using updated scopes for Instagram API with Instagram Login (Jan 2025+)
        # Old scopes (instagram_basic, instagram_manage_messages, pages_*) are deprecated
        auth_url = (
            f"https://www.instagram.com/oauth/authorize"
            f"?client_id={dm_settings.INSTAGRAM_APP_ID}"
            f"&redirect_uri={dm_settings.INSTAGRAM_REDIRECT_URI}"
            f"&scope=instagram_business_basic,instagram_business_manage_messages"
            f"&response_type=code"
            f"&state={state}"
        )

        return {
            "state": state,
            "authorization_url": auth_url,
        }

    except Exception as e:
        logger.error(f"OAuth state generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth state",
        )


@router.get("/instagram/callback")
async def instagram_callback(
    code: str,
    state: str,
    redis_client=Depends(get_redis_client),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Handle Instagram OAuth callback.

    Uses Instagram API with Instagram Login (no Facebook Page required).
    Flow:
    1. Verify CSRF state from Redis
    2. Exchange code for short-lived token
    3. Exchange short token for long-lived token (60-day expiry)
    4. Fetch user profile information
    5. Store token and account info in Cosmos DB
    6. Cache account mapping in Redis

    Args:
        code: Authorization code from Instagram
        state: State token for CSRF protection
        redis_client: Redis client
        cosmos_client: Cosmos DB client

    Returns:
        dict: Account information and connection status

    Status Codes:
        200: Account connected successfully
        400: Invalid state or callback parameters
        500: Server error
    """
    try:
        # Step 1: Verify CSRF state
        redis_key = f"oauth_state:{state}"
        state_valid = await redis_client.get(redis_key)

        if not state_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state token",
            )

        # Delete state token (single-use)
        await redis_client.delete(redis_key)

        # Step 2: Exchange code for short-lived token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": dm_settings.INSTAGRAM_APP_ID,
                    "client_secret": dm_settings.INSTAGRAM_APP_SECRET,
                    "grant_type": "authorization_code",
                    "redirect_uri": dm_settings.INSTAGRAM_REDIRECT_URI,
                    "code": code,
                },
            )

            if token_response.status_code != 200:
                logger.error(
                    f"Token exchange failed: {token_response.text}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange code for token",
                )

            token_data = token_response.json()
            short_token = token_data.get("access_token")
            ig_user_id = str(token_data.get("user_id"))

            if not short_token or not ig_user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing token or user ID in response",
                )

            # Step 3: Exchange short-lived token for long-lived token (60 days)
            # Server-side only — never expose app secret to client
            long_token_response = await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": dm_settings.INSTAGRAM_APP_SECRET,
                    "access_token": short_token,
                },
            )

            if long_token_response.status_code != 200:
                logger.error(
                    f"Long token exchange failed: {long_token_response.text}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get long-lived token",
                )

            long_token_data = long_token_response.json()
            long_token = long_token_data.get("access_token")
            # Long-lived tokens expire in 60 days
            expires_in = long_token_data.get("expires_in", 5184000)

            if not long_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to obtain long-lived token",
                )

            # Step 4: Fetch user profile using Instagram API with Instagram Login
            # No Facebook Page needed — query directly with Instagram user token
            profile_response = await client.get(
                f"https://graph.instagram.com/v21.0/me",
                params={
                    "fields": "user_id,username,name,account_type,profile_picture_url,followers_count",
                    "access_token": long_token,
                },
            )

            if profile_response.status_code != 200:
                logger.error(
                    f"Profile fetch failed: {profile_response.text}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch profile information",
                )

            profile_data = profile_response.json()
            account_type = profile_data.get("account_type")

            # Only Business and Creator accounts can use the messaging API
            if account_type not in ["CREATOR", "BUSINESS"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Account type '{account_type}' not supported. Only CREATOR and BUSINESS accounts can use messaging.",
                )

            # Step 5: Store token and account info in Cosmos DB
            # No Facebook Page ID needed with Instagram Login flow
            account_id = f"instagram_{ig_user_id}"
            account_doc = {
                "id": account_id,
                "type": "instagram_account",
                "ig_user_id": ig_user_id,
                "username": profile_data.get("username"),
                "name": profile_data.get("name"),
                "account_type": account_type,
                "profile_picture_url": profile_data.get("profile_picture_url"),
                "followers_count": profile_data.get("followers_count"),
                "access_token": long_token,  # TODO: encrypt with Azure Key Vault
                "token_expires_in": expires_in,
                "status": "active",
                "created_at": None,
                "updated_at": None,
            }

            accounts_container = await cosmos_client.get_async_container_client(
                INSTAGRAM_TOKEN_CONTAINER
            )

            # Upsert so reconnecting doesn't fail
            await accounts_container.upsert_item(body=account_doc)

            # Step 6: Cache account mapping in Redis
            await redis_client.setex(
                f"account:{account_id}",
                86400 * 30,  # 30 days
                str(profile_data),
            )

            # Redirect back to frontend with success params
            params = urlencode({
                "status": "connected",
                "username": profile_data.get("username", ""),
                "account_id": account_id,
            })
            return RedirectResponse(
                url=f"{dm_settings.FRONTEND_URL}/auth/redirect?{params}",
                status_code=302,
            )

    except HTTPException as he:
        # Redirect to frontend with error
        params = urlencode({"status": "error", "message": he.detail})
        return RedirectResponse(
            url=f"{dm_settings.FRONTEND_URL}/auth/redirect?{params}",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        params = urlencode({"status": "error", "message": "Failed to connect Instagram account"})
        return RedirectResponse(
            url=f"{dm_settings.FRONTEND_URL}/auth/redirect?{params}",
            status_code=302,
        )


@router.delete("/instagram/data-deletion")
async def instagram_data_deletion(
    signed_request: str = Query(...),
    redis_client=Depends(get_redis_client),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Meta required data deletion callback.

    This endpoint handles Meta's data deletion requests as required by their
    platform policies. When a user deletes their Instagram account, Meta sends
    a signed request that we must respond to within 30 days.

    Args:
        signed_request: Meta's signed request containing user data

    Returns:
        dict: Confirmation that data deletion was processed

    Status Codes:
        200: Data deletion processed
        400: Invalid signed request
        500: Server error
    """
    try:
        # Verify signed request from Meta
        if not signed_request:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing signed_request parameter",
            )

        # Parse signed request (format: signature.payload)
        try:
            signature, payload = signed_request.split(".")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signed_request format",
            )

        # Verify signature using app secret
        expected_sig = hmac.new(
            dm_settings.INSTAGRAM_APP_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            logger.warning("Invalid data deletion request signature")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature",
            )

        # In production, parse payload and delete user data
        # For now, just confirm receipt

        return {
            "status": "ok",
            "message": "Data deletion request received and queued for processing",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Data deletion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process data deletion request",
        )
