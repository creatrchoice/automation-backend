"""Authentication routes for DM Automation API."""
import logging
import hmac
import hashlib
import secrets
import uuid
from typing import Optional
from datetime import datetime, timedelta, timezone

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from fastapi import APIRouter, Request, status, Depends, Query
from fastapi.responses import RedirectResponse
import httpx
import ssl
from urllib.parse import urlencode

from redis.exceptions import RedisError

from app.core.config import dm_settings
from app.core.errors import (
    ValidationError,
    InvalidCredentialsError,
    DuplicateEntityError,
    BadRequestError,
    InternalServerError,
    ExternalServiceError,
)
from app.api.deps import (
    get_redis_client,
    get_cosmos_client,
    create_access_token,
    get_current_user,
)
from app.db.cosmos_containers import (
    CONTAINER_USERS,
    CONTAINER_IG_ACCOUNTS,
    CONTAINER_ORGANIZATIONS,
    CONTAINER_OAUTH_STATES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Constants
CSRF_STATE_EXPIRY = 600  # 10 minutes
INSTAGRAM_TOKEN_CONTAINER = CONTAINER_IG_ACCOUNTS
USERS_CONTAINER = CONTAINER_USERS


def _oauth_expires_at_utc(expires_raw) -> Optional[datetime]:
    """Parse expires_at from Cosmos (ISO string) to timezone-aware UTC."""
    if not expires_raw:
        return None
    try:
        s = str(expires_raw).replace("Z", "+00:00") if str(expires_raw).endswith("Z") else str(expires_raw)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


async def _store_oauth_state_cosmos(cosmos_client, state: str, user_id: str) -> None:
    """Persist OAuth CSRF state when Redis is unavailable (partition key = id = state)."""
    container = await cosmos_client.get_async_container_client(CONTAINER_OAUTH_STATES)
    expires = datetime.now(timezone.utc) + timedelta(seconds=CSRF_STATE_EXPIRY)
    await container.upsert_item(
        body={
            "id": state,
            "user_id": user_id,
            "expires_at": expires.isoformat(),
            "type": "oauth_state",
        }
    )


async def _consume_oauth_state_cosmos(cosmos_client, state: str) -> Optional[str]:
    """
    Read and delete OAuth state document; return user_id if valid and not expired.
    """
    container = await cosmos_client.get_async_container_client(CONTAINER_OAUTH_STATES)
    try:
        doc = await container.read_item(item=state, partition_key=state)
    except CosmosResourceNotFoundError:
        return None

    exp = _oauth_expires_at_utc(doc.get("expires_at"))
    if exp is not None and datetime.now(timezone.utc) > exp:
        try:
            await container.delete_item(item=state, partition_key=state)
        except CosmosResourceNotFoundError:
            pass
        return None

    uid = doc.get("user_id")
    if uid is None:
        try:
            await container.delete_item(item=state, partition_key=state)
        except CosmosResourceNotFoundError:
            pass
        return None

    try:
        await container.delete_item(item=state, partition_key=state)
    except CosmosResourceNotFoundError:
        pass
    return str(uid)


async def _ensure_instagram_not_linked_to_other_user(
    accounts_container,
    ig_user_id: str,
    owner_user_id: str,
) -> None:
    """
    Enforce: one Instagram professional account (ig_user_id) → at most one app user.

    - A single app user may connect many Instagram accounts (many Cosmos docs with the
      same user_id and different ig_user_id / id).
    - The same ig_user_id must not appear on a document owned by a different user_id.
    - Same user reconnecting the same IG (upsert) is allowed.
    """
    query = "SELECT c.id, c.user_id FROM c WHERE c.ig_user_id = @ig_user_id"
    async for row in accounts_container.query_items(
        query=query,
        parameters=[{"name": "@ig_user_id", "value": ig_user_id}],
        enable_cross_partition_query=True,
    ):
        if row.get("user_id") != owner_user_id:
            logger.warning(
                "Instagram ig_user_id=%s already linked to user_id=%s; connect attempt by %s rejected",
                ig_user_id,
                row.get("user_id"),
                owner_user_id,
            )
            raise DuplicateEntityError(
                message=f"Instagram account {ig_user_id} already linked to another app user",
                user_title="Instagram Already Connected",
                user_message=(
                    "This Instagram account is already connected to another user. "
                    "Disconnect it from that account first, or use a different Instagram account."
                ),
            )


async def _find_user_org_id(cosmos_client, user_id: str) -> Optional[str]:
    """Look up the user's organization id (if any). Returns None if not a member of any org."""
    try:
        org_container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
        query = "SELECT o.id FROM o JOIN m IN o.members WHERE m.user_id = @uid"
        async for item in org_container.query_items(
            query=query,
            parameters=[{"name": "@uid", "value": user_id}],
        ):
            return item.get("id")
    except Exception as e:
        logger.error(f"Could not look up org for user {user_id}: {e}", exc_info=True)
    return None


async def _subscribe_webhook_events(ig_user_id: str, access_token: str) -> bool:
    """
    Subscribe the connected Instagram account to webhook events.

    Calls Meta's subscribed_apps endpoint so we receive real-time events
    for messages, messaging_postbacks, and comments on this account.

    This is a best-effort operation — if it fails, the account is still
    connected and we log the error for manual retry.

    Args:
        ig_user_id: The Instagram user ID (numeric string)
        access_token: Long-lived access token for the account
    """
    subscribed_fields = "messages,messaging_postbacks,comments"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://graph.instagram.com/v21.0/{ig_user_id}/subscribed_apps",
                params={
                    "subscribed_fields": subscribed_fields,
                    "access_token": access_token,
                },
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info(
                        f"Webhook subscription successful for IG account {ig_user_id} "
                        f"(fields: {subscribed_fields})"
                    )
                    return True
                else:
                    logger.warning(
                        f"Webhook subscription returned non-success for {ig_user_id}: {result}"
                    )
                    return False
            else:
                logger.error(
                    f"Webhook subscription failed for {ig_user_id}: "
                    f"status={response.status_code}, body={response.text}"
                )
                return False

    except Exception as e:
        # Don't fail the entire OAuth flow if webhook subscription fails.
        # The account is still connected — we can retry subscription later.
        logger.error(
            f"Webhook subscription error for {ig_user_id}: {e}",
            exc_info=True,
        )
        return False


@router.post("/instagram/{account_id}/subscribe-webhooks")
async def subscribe_webhooks_for_account(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Manually trigger webhook subscription for an existing connected Instagram account.

    Usage:
        curl -X POST https://automationapi.creatrchoice.info/auth/instagram/{account_id}/subscribe-webhooks \
             -H "Authorization: Bearer <JWT_TOKEN>"
    """
    try:
        # Fetch the account from DB
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )

        # Partition key for dm_ig_accounts is /user_id
        owner_user_id = current_user.get("sub")

        try:
            account = await accounts_container.read_item(
                item=account_id,
                partition_key=owner_user_id,
            )
        except Exception:
            raise BadRequestError(
                message=f"Account {account_id} not found for user {owner_user_id}",
                user_title="Account Not Found",
                user_message=f"Instagram account '{account_id}' was not found.",
            )

        ig_user_id = account.get("ig_user_id")
        access_token = account.get("access_token")

        if not ig_user_id or not access_token:
            raise BadRequestError(
                message="Missing ig_user_id or access_token",
                user_title="Incomplete Account",
                user_message="This account is missing required data for webhook subscription.",
            )

        # Subscribe to webhooks
        success = await _subscribe_webhook_events(ig_user_id, access_token)

        if success:
            # Update DB
            account["webhook_subscribed"] = True
            account["webhook_fields"] = ["messages", "messaging_postbacks", "comments"]
            await accounts_container.upsert_item(body=account)

            return {
                "status": "subscribed",
                "account_id": account_id,
                "ig_user_id": ig_user_id,
                "username": account.get("username"),
                "webhook_fields": ["messages", "messaging_postbacks", "comments"],
            }
        else:
            raise ExternalServiceError(
                service="Instagram",
                message=f"Webhook subscription failed for {ig_user_id}",
                user_message="Could not subscribe to Instagram webhook events. Check logs for details.",
            )

    except (BadRequestError, ExternalServiceError):
        raise
    except Exception as e:
        logger.error(f"Webhook subscription endpoint error: {e}", exc_info=True)
        raise InternalServerError(
            message=f"Webhook subscription error: {e}",
            user_title="Subscription Failed",
            user_message="Failed to subscribe to webhook events. Please try again.",
        )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    email: str,
    password: str,
    cosmos_client=Depends(get_cosmos_client),
    redis_client=Depends(get_redis_client),
):
    """Sign up new user with email and password."""
    # Validate email format
    if not email or "@" not in email:
        raise ValidationError(
            message="Invalid email format",
            user_title="Invalid Email",
            user_message="Please enter a valid email address.",
        )

    # Validate password length
    if len(password) < 8:
        raise ValidationError(
            message="Password too short",
            user_title="Weak Password",
            user_message="Password must be at least 8 characters long.",
        )

    try:
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
            raise DuplicateEntityError(
                message=f"User with email {email} already exists",
                user_title="Account Exists",
                user_message="An account with this email already exists. Please sign in instead.",
            )

        # Hash password
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # Create user document
        user_id = email.replace("@", "_").replace(".", "_")
        user_doc = {
            "id": user_id,
            "partition_key": "user",
            "email": email,
            "password_hash": password_hash,
            "created_at": None,
            "updated_at": None,
            "connected_accounts": [],
        }

        # Store in Cosmos DB
        await users_container.create_item(body=user_doc)

        # Check if user is already a member of an org (e.g. invited before signup)
        org_id = await _find_user_org_id(cosmos_client, user_id)

        # Auto-create an organization if the user doesn't have one
        if not org_id:
            now = datetime.now(timezone.utc).isoformat()
            org_id = str(uuid.uuid4())
            org_name = email.split("@")[0] + "'s Team"
            org_doc = {
                "id": org_id,
                "name": org_name,
                "created_by": user_id,
                "members": [
                    {
                        "user_id": user_id,
                        "email": email,
                        "role": "owner",
                        "joined_at": now,
                    }
                ],
                "created_at": now,
                "updated_at": now,
            }
            org_container = await cosmos_client.get_async_container_client(
                CONTAINER_ORGANIZATIONS
            )
            await org_container.create_item(body=org_doc)

        # Create JWT token with org_id
        access_token = create_access_token(
            data={"sub": user_id, "email": email, "org_id": org_id},
            expires_delta=timedelta(hours=24),
        )

        return {
            "message": "User created successfully",
            "user_id": user_id,
            "email": email,
            "org_id": org_id,
            "access_token": access_token,
            "token_type": "bearer",
        }

    except (ValidationError, DuplicateEntityError):
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise InternalServerError(
            message=f"Signup failed: {e}",
            user_title="Signup Failed",
            user_message="We couldn't create your account right now. Please try again later.",
        )


@router.post("/login")
async def login(
    email: str,
    password: str,
    cosmos_client=Depends(get_cosmos_client),
):
    """Log in user with email and password."""
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
            raise InvalidCredentialsError()

        user = users[0]

        # Verify password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if user.get("password_hash") != password_hash:
            raise InvalidCredentialsError()

        # Look up organization membership
        org_id = await _find_user_org_id(cosmos_client, user["id"])

        # Create JWT token
        token_data = {"sub": user["id"], "email": user["email"]}
        if org_id:
            token_data["org_id"] = org_id

        access_token = create_access_token(
            data=token_data,
            expires_delta=timedelta(hours=24),
        )

        return {
            "message": "Login successful",
            "user_id": user["id"],
            "email": user["email"],
            "org_id": org_id,
            "access_token": access_token,
            "token_type": "bearer",
        }

    except InvalidCredentialsError:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise InternalServerError(
            message=f"Login failed: {e}",
            user_title="Login Failed",
            user_message="We couldn't sign you in right now. Please try again later.",
        )


@router.get("/instagram/state")
async def get_instagram_state(
    current_user: dict = Depends(get_current_user),
    redis_client=Depends(get_redis_client),
    cosmos_client=Depends(get_cosmos_client),
):
    """Generate CSRF state token for Instagram OAuth flow.

    Stores state in Redis when possible; falls back to Cosmos DB (`dm_oauth_states`)
    if Redis is down or misconfigured (e.g. TLS issues on Redis Cloud).
    """
    try:
        state = secrets.token_urlsafe(32)
        user_id = current_user.get("sub")

        redis_key = f"oauth_state:{state}"
        stored_in_redis = False
        try:
            await redis_client.setex(redis_key, CSRF_STATE_EXPIRY, user_id)
            stored_in_redis = True
        except (RedisError, ssl.SSLError, OSError) as e:
            logger.warning(
                "OAuth state: Redis unavailable (%s); storing CSRF state in Cosmos DB",
                e,
            )

        if not stored_in_redis:
            await _store_oauth_state_cosmos(cosmos_client, state, user_id)

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
        logger.error(f"OAuth state generation error: {e}", exc_info=True)
        raise InternalServerError(
            message=f"OAuth state generation failed: {e}",
            user_title="Connection Error",
            user_message="Couldn't start Instagram connection. Please try again.",
        )


@router.get("/instagram/callback")
async def instagram_callback(
    request: Request,
    code: str,
    state: str,
    redis_client=Depends(get_redis_client),
    cosmos_client=Depends(get_cosmos_client),
):
    """Handle Instagram OAuth callback (Instagram Login flow, no Facebook Page required)."""
    try:
        # Step 1: Verify CSRF state (Redis first, then Cosmos fallback)
        redis_key = f"oauth_state:{state}"
        owner_user_id: Optional[str] = None

        try:
            state_valid = await redis_client.get(redis_key)
            if state_valid:
                owner_user_id = (
                    state_valid.decode()
                    if isinstance(state_valid, bytes)
                    else str(state_valid)
                )
                await redis_client.delete(redis_key)
        except (RedisError, ssl.SSLError, OSError) as e:
            logger.warning("OAuth callback: Redis unavailable (%s); trying Cosmos for CSRF state", e)

        if not owner_user_id:
            owner_user_id = await _consume_oauth_state_cosmos(cosmos_client, state)

        if not owner_user_id:
            raise BadRequestError(
                message="Invalid or expired OAuth state",
                user_title="Session Expired",
                user_message="Your connection session has expired. Please try connecting again.",
            )

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
                logger.error(f"Token exchange failed: {token_response.text}")
                raise ExternalServiceError(
                    service="Instagram",
                    message=f"Token exchange failed: {token_response.text}",
                    user_message="Instagram couldn't verify your authorization. Please try again.",
                )

            token_data = token_response.json()
            short_token = token_data.get("access_token")
            ig_user_id = str(token_data.get("user_id"))

            if not short_token or not ig_user_id:
                raise BadRequestError(
                    message="Missing token or user ID from Instagram",
                    user_message="Instagram returned an incomplete response. Please try again.",
                )

            # Step 3: Exchange for long-lived token (60 days)
            long_token_response = await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": dm_settings.INSTAGRAM_APP_SECRET,
                    "access_token": short_token,
                },
            )

            if long_token_response.status_code != 200:
                logger.error(f"Long token exchange failed: {long_token_response.text}")
                raise ExternalServiceError(
                    service="Instagram",
                    message=f"Long token exchange failed: {long_token_response.text}",
                    user_message="Couldn't complete Instagram authorization. Please try again.",
                )

            long_token_data = long_token_response.json()
            long_token = long_token_data.get("access_token")
            expires_in = long_token_data.get("expires_in", 5184000)

            if not long_token:
                raise BadRequestError(
                    message="Failed to obtain long-lived token",
                    user_message="Couldn't complete authorization with Instagram.",
                )

            # Step 4: Fetch user profile
            profile_response = await client.get(
                f"https://graph.instagram.com/v21.0/me",
                params={
                    "fields": "user_id,username,name,account_type,profile_picture_url,followers_count",
                    "access_token": long_token,
                },
            )

            if profile_response.status_code != 200:
                logger.error(f"Profile fetch failed: {profile_response.text}")
                raise ExternalServiceError(
                    service="Instagram",
                    message=f"Profile fetch failed: {profile_response.text}",
                    user_message="Couldn't fetch your Instagram profile. Please try again.",
                )

            profile_data = profile_response.json()
            account_type = profile_data.get("account_type")

            if account_type not in ["CREATOR", "BUSINESS"]:
                raise BadRequestError(
                    message=f"Unsupported account type: {account_type}",
                    user_title="Account Not Supported",
                    user_message="Only Creator and Business Instagram accounts can use messaging automation. Please switch your account type and try again.",
                )

            accounts_container = await cosmos_client.get_async_container_client(
                INSTAGRAM_TOKEN_CONTAINER
            )
            await _ensure_instagram_not_linked_to_other_user(
                accounts_container,
                ig_user_id,
                owner_user_id,
            )

            # Step 5: Store in Cosmos DB
            account_id = f"instagram_{ig_user_id}"
            account_doc = {
                "id": account_id,
                "account_id": account_id,
                "user_id": owner_user_id,
                "type": "instagram_account",
                "ig_user_id": ig_user_id,
                "username": profile_data.get("username"),
                "name": profile_data.get("name"),
                "account_type": account_type,
                "profile_picture_url": profile_data.get("profile_picture_url"),
                "followers_count": profile_data.get("followers_count"),
                "access_token": long_token,
                "token_expires_in": expires_in,
                "status": "active",
                "created_at": None,
                "updated_at": None,
            }

            await accounts_container.upsert_item(body=account_doc)

            # Step 6: Subscribe to webhook events (messages, messaging_postbacks, comments)
            webhook_ok = await _subscribe_webhook_events(
                ig_user_id=ig_user_id,
                access_token=long_token,
            )

            # Update account doc with webhook subscription status
            if webhook_ok:
                account_doc["webhook_subscribed"] = True
                account_doc["webhook_fields"] = ["messages", "messaging_postbacks", "comments"]
                await accounts_container.upsert_item(body=account_doc)

            # Step 7: Cache in Redis
            await redis_client.setex(
                f"account:{account_id}",
                86400 * 30,
                str(profile_data),
            )

            # Check if called from frontend API (wants JSON) or browser redirect (Instagram)
            is_api_call = "application/json" in request.headers.get("accept", "")

            result = {
                "status": "connected",
                "username": profile_data.get("username", ""),
                "account_id": account_id,
            }

            if is_api_call:
                return result

            params = urlencode(result)
            return RedirectResponse(
                url=f"{dm_settings.FRONTEND_URL}/auth/redirect?{params}",
                status_code=302,
            )

    except (BadRequestError, ExternalServiceError, DuplicateEntityError) as exc:
        is_api_call = "application/json" in request.headers.get("accept", "")
        if is_api_call:
            raise exc

        params = urlencode({"status": "error", "message": exc.user_message})
        return RedirectResponse(
            url=f"{dm_settings.FRONTEND_URL}/auth/redirect?{params}",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        is_api_call = "application/json" in request.headers.get("accept", "")
        if is_api_call:
            raise InternalServerError(
                message=f"OAuth callback error: {e}",
                user_title="Connection Failed",
                user_message="Failed to connect Instagram account. Please try again.",
            )

        params = urlencode({"status": "error", "message": "Failed to connect Instagram account. Please try again."})
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
    """Meta required data deletion callback."""
    if not signed_request:
        raise BadRequestError(
            message="Missing signed_request parameter",
            user_message="Invalid data deletion request.",
        )

    try:
        signature, payload = signed_request.split(".")
    except ValueError:
        raise BadRequestError(
            message="Invalid signed_request format",
            user_message="Invalid data deletion request format.",
        )

    expected_sig = hmac.new(
        dm_settings.INSTAGRAM_APP_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        logger.warning("Invalid data deletion request signature")
        raise BadRequestError(
            message="Invalid signature on data deletion request",
            user_message="Could not verify the data deletion request.",
        )

    return {
        "status": "ok",
        "message": "Data deletion request received and queued for processing",
    }
