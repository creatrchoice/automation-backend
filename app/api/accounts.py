"""Account management routes for connected Instagram accounts."""
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Depends, Query
import httpx

from app.core.config import dm_settings as settings
from app.api.deps import (
    get_current_user,
    get_cosmos_client,
    get_redis_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["Accounts"])

from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS
INSTAGRAM_TOKEN_CONTAINER = CONTAINER_IG_ACCOUNTS


@router.get("")
async def list_accounts(
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    """
    List all connected Instagram accounts for current user.

    Args:
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client
        skip: Number of results to skip (pagination)
        limit: Maximum number of results to return

    Returns:
        dict: List of connected accounts with metadata

    Status Codes:
        200: Success
        401: Unauthorized
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Query connected accounts for user
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )

        query = (
            "SELECT * FROM accounts "
            "WHERE accounts.user_id = @user_id AND accounts.status != 'deleted' "
            "ORDER BY accounts.created_at DESC "
            f"OFFSET {skip} LIMIT {limit}"
        )

        accounts = []
        async for item in accounts_container.query_items(
            query=query,
            parameters=[{"name": "@user_id", "value": user_id}],
        ):
            # Remove sensitive data before returning
            item.pop("access_token", None)
            accounts.append(item)

        # Get total count
        count_query = (
            "SELECT VALUE COUNT(1) FROM accounts "
            "WHERE accounts.user_id = @user_id AND accounts.status != 'deleted'"
        )
        total_count = 0
        async for item in accounts_container.query_items(
            query=count_query,
            parameters=[{"name": "@user_id", "value": user_id}],
        ):
            total_count = item

        return {
            "accounts": accounts,
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }

    except Exception as e:
        logger.error(f"Error listing accounts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list accounts",
        )


@router.get("/{account_id}")
async def get_account(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get details for a specific connected account.

    Args:
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Account details

    Status Codes:
        200: Success
        401: Unauthorized
        404: Account not found
        403: Account not owned by current user
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )

        # Fetch account
        query = "SELECT * FROM accounts WHERE accounts.id = @account_id"
        accounts = []
        async for item in accounts_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            accounts.append(item)

        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        account = accounts[0]

        # Verify ownership
        if account.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Remove sensitive data
        account.pop("access_token", None)

        return account

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get account",
        )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    redis_client=Depends(get_redis_client),
):
    """
    Disconnect a connected Instagram account.

    Disconnection process:
    1. Pause all automations for this account
    2. Unsubscribe from webhooks
    3. Soft delete account (set status to 'deleted')
    4. Clear Redis cache

    Args:
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client
        redis_client: Redis client

    Status Codes:
        204: Account disconnected successfully
        401: Unauthorized
        404: Account not found
        403: Account not owned by current user
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )

        # Fetch account
        query = "SELECT * FROM accounts WHERE accounts.id = @account_id"
        accounts = []
        async for item in accounts_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            accounts.append(item)

        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        account = accounts[0]

        # Verify ownership
        if account.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Step 1: Pause all automations
        automations_container = await cosmos_client.get_async_container_client(
            "automations"
        )
        pause_query = (
            "SELECT * FROM automations "
            "WHERE automations.account_id = @account_id AND automations.status = 'active'"
        )

        automations = []
        async for item in automations_container.query_items(
            query=pause_query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            automations.append(item)

        # Update automations to paused
        for automation in automations:
            automation["status"] = "paused"
            await automations_container.replace_item(
                item=automation["id"],
                body=automation,
                partition_key=automation.get("user_id"),
            )

        # Step 2: Unsubscribe from webhooks
        page_id = account.get("page_id")
        access_token = account.get("access_token")

        if page_id and access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.delete(
                        f"https://graph.instagram.com/v21.0/{page_id}/subscribed_apps",
                        params={"access_token": access_token},
                    )
            except Exception as e:
                logger.warning(f"Failed to unsubscribe from webhooks: {e}")

        # Step 3: Soft delete account
        account["status"] = "deleted"
        await accounts_container.replace_item(
            item=account_id,
            body=account,
            partition_key=user_id,
        )

        # Step 4: Clear Redis cache
        await redis_client.delete(f"account:{account_id}")

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting account: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect account",
        )
