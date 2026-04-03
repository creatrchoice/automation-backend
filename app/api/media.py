"""Instagram media fetch routes.

Proxies requests to the Instagram Graph API to list a user's posts,
reels, carousel albums, and (optionally) active stories.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
import httpx

from app.core.config import dm_settings as settings
from app.core.errors import (
    ExternalServiceError,
    ForbiddenError,
    InternalServerError,
)
from app.api.deps import get_current_user, get_cosmos_client, get_redis_client
from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["Media"])

GRAPH_BASE = settings.INSTAGRAM_API_BASE_URL
API_VERSION = settings.INSTAGRAM_API_VERSION

# Fields we request from the Graph API
MEDIA_FIELDS = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"


async def _get_account_with_token(
    account_id: str,
    user_id: str,
    cosmos_client,
) -> dict:
    """Fetch an Instagram account doc and verify ownership. Returns full doc (with token).

    Uses partition_key=user_id so Cosmos DB routes to the correct partition.
    (dm_ig_accounts is partitioned by /user_id; querying by id without the
    partition key can land in the wrong partition and return a foreign document.)
    """
    container = await cosmos_client.get_async_container_client(CONTAINER_IG_ACCOUNTS)

    query = (
        "SELECT * FROM a "
        "WHERE a.id = @account_id AND a.user_id = @user_id"
    )
    accounts = []
    async for item in container.query_items(
        query=query,
        parameters=[
            {"name": "@account_id", "value": account_id},
            {"name": "@user_id", "value": user_id},
        ],
        partition_key=user_id,
    ):
        accounts.append(item)

    if not accounts:
        raise ForbiddenError("Account not found or access denied.")

    account = accounts[0]

    if not account.get("access_token"):
        raise ExternalServiceError(
            service="Instagram",
            message="No access token found for this account. Please reconnect.",
            user_message="Your Instagram account needs to be reconnected.",
        )

    return account


@router.get("/{account_id}")
async def list_media(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    redis_client=Depends(get_redis_client),
    after: Optional[str] = Query(None, description="Pagination cursor (next page)"),
    limit: int = Query(25, ge=1, le=100, description="Number of media items to fetch"),
):
    """
    List Instagram media (posts, reels, carousels) for a connected account.

    Calls GET /{ig_user_id}/media on the Instagram Graph API and returns
    the results along with pagination cursors.

    Returns:
        {
            "media": [ { id, caption, media_type, media_url, thumbnail_url, permalink, timestamp } ],
            "paging": { "next_cursor": "...", "has_next": true }
        }
    """
    user_id = current_user.get("sub")
    account = await _get_account_with_token(account_id, user_id, cosmos_client)

    ig_user_id = account.get("ig_user_id")
    access_token = account["access_token"]

    # Check Redis cache first
    cache_key = f"media:{account_id}:after={after or 'start'}:limit={limit}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
    except Exception:
        pass  # Cache miss or Redis error — continue with live fetch

    # Call Instagram Graph API
    params = {
        "fields": MEDIA_FIELDS,
        "limit": limit,
        "access_token": access_token,
    }
    if after:
        params["after"] = after

    url = f"{GRAPH_BASE}/{API_VERSION}/{ig_user_id}/media"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)

        if resp.status_code != 200:
            try:
                err_body = resp.json()
            except Exception:
                err_body = {}

            ig_error = err_body.get("error", {})
            ig_code = ig_error.get("code")
            ig_subcode = ig_error.get("error_subcode")
            ig_msg = ig_error.get("message", "Unknown Instagram error")

            logger.error(
                f"Instagram API error for account {account_id}: "
                f"HTTP {resp.status_code} | code={ig_code} sub={ig_subcode} | {ig_msg}"
            )

            # Token expired / invalid (code 190) or auth error (401)
            if resp.status_code == 401 or ig_code == 190:
                raise ExternalServiceError(
                    service="Instagram",
                    message=f"Instagram token expired/invalid: code={ig_code} sub={ig_subcode} {ig_msg}",
                    user_message="Your Instagram session has expired. Please reconnect your account.",
                )

            raise ExternalServiceError(
                service="Instagram",
                message=f"Instagram API returned {resp.status_code}: {ig_msg}",
                user_message="Failed to load your Instagram posts. Please try again.",
            )

        data = resp.json()

    except httpx.TimeoutException:
        raise ExternalServiceError(
            service="Instagram",
            message="Instagram API request timed out",
            user_message="Instagram is taking too long to respond. Please try again.",
        )
    except ExternalServiceError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error calling Instagram API: {e}")
        raise InternalServerError(
            message=f"Error fetching media: {e}",
            user_message="Something went wrong while loading your posts.",
        )

    # Parse response
    media_items = data.get("data", [])
    paging = data.get("paging", {})
    cursors = paging.get("cursors", {})

    result = {
        "media": media_items,
        "paging": {
            "next_cursor": cursors.get("after"),
            "has_next": "next" in paging,
        },
    }

    # Cache for 5 minutes
    try:
        import json
        await redis_client.set(cache_key, json.dumps(result), ex=300)
    except Exception:
        pass  # Non-critical

    return result


@router.get("/{account_id}/stories")
async def list_stories(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    List currently active Instagram stories for a connected account.

    Stories are ephemeral (24h) so this returns only live stories.

    Returns:
        { "stories": [ { id, media_type, media_url, timestamp } ] }
    """
    user_id = current_user.get("sub")
    account = await _get_account_with_token(account_id, user_id, cosmos_client)

    ig_user_id = account.get("ig_user_id")
    access_token = account["access_token"]

    url = f"{GRAPH_BASE}/{API_VERSION}/{ig_user_id}/stories"
    params = {
        "fields": "id,media_type,media_url,thumbnail_url,timestamp",
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)

        if resp.status_code != 200:
            try:
                err_body = resp.json()
            except Exception:
                err_body = {}
            ig_error = err_body.get("error", {})
            ig_code = ig_error.get("code")
            ig_msg = ig_error.get("message", "Unknown error")
            logger.error(
                f"Instagram stories API error: HTTP {resp.status_code} | code={ig_code} | {ig_msg}"
            )
            if resp.status_code == 401 or ig_code == 190:
                raise ExternalServiceError(
                    service="Instagram",
                    message=f"Instagram token expired/invalid for stories: {ig_msg}",
                    user_message="Your Instagram session has expired. Please reconnect your account.",
                )
            raise ExternalServiceError(
                service="Instagram",
                message=f"Instagram stories API returned {resp.status_code}: {ig_msg}",
                user_message="Failed to load your stories. Please try again.",
            )

        data = resp.json()

    except ExternalServiceError:
        raise
    except Exception as e:
        logger.error(f"Error fetching stories: {e}")
        raise InternalServerError(
            message=f"Error fetching stories: {e}",
            user_message="Something went wrong while loading your stories.",
        )

    return {
        "stories": data.get("data", []),
    }
