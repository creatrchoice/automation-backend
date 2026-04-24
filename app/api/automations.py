"""Automation management routes for DM automation workflows."""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends, Query

from app.api.deps import (
    get_current_user,
    get_cosmos_client,
    get_redis_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automations", tags=["Automations"])

from app.db.cosmos_containers import CONTAINER_AUTOMATIONS, CONTAINER_IG_ACCOUNTS
AUTOMATIONS_CONTAINER = CONTAINER_AUTOMATIONS
INSTAGRAM_TOKEN_CONTAINER = CONTAINER_IG_ACCOUNTS


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_automation(
    account_id: str,
    name: str,
    trigger: Dict[str, Any],
    conditions: Optional[List[Dict[str, Any]]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Create a new DM automation for an Instagram account.

    Args:
        account_id: Instagram account ID
        name: Automation name
        trigger: Trigger configuration (e.g., {"type": "message_received", "keywords": ["hello"]})
        conditions: Optional list of conditions to check
        steps: Optional list of automation steps to execute
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Created automation with ID and metadata

    Status Codes:
        201: Automation created successfully
        400: Invalid input
        401: Unauthorized
        404: Account not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Verify account ownership using partition key for correct Cosmos DB routing
        # (dm_ig_accounts is partitioned by /user_id — querying by id without
        #  the partition key can route to the wrong partition and return a
        #  document belonging to a different user)
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )
        query = (
            "SELECT * FROM accounts "
            "WHERE accounts.id = @account_id AND accounts.user_id = @user_id"
        )
        accounts = []
        async for item in accounts_container.query_items(
            query=query,
            parameters=[
                {"name": "@account_id", "value": account_id},
                {"name": "@user_id", "value": user_id},
            ],
            partition_key=user_id,
        ):
            accounts.append(item)

        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not found or access denied",
            )

        # Validate input
        if not name or not trigger:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Name and trigger are required",
            )

        # Create automation document
        automation_id = f"automation_{account_id}_{datetime.utcnow().timestamp()}"
        automation_doc = {
            "id": automation_id,
            "type": "dm_automation",
            "user_id": user_id,
            "account_id": account_id,
            "name": name,
            "trigger": trigger,
            "conditions": conditions or [],
            "steps": steps or [],
            "status": "active",
            "enabled": True,
            "run_count": 0,
            "error_count": 0,
            "created_at": None,
            "updated_at": None,
        }

        tr = trigger or {}
        tt_raw = tr.get("type") or "message_received"
        tt = tt_raw.lower().replace("-", "_") if isinstance(tt_raw, str) else "message_received"
        if tt in ("keyword",):
            tt = "dm_keyword"
        if tt == "message_received" and (tr.get("keywords") or []):
            automation_doc["automation_type"] = "dm_keyword"
        else:
            automation_doc["automation_type"] = tt

        # Store in Cosmos DB
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )
        await automations_container.create_item(body=automation_doc)

        return automation_doc

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating automation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create automation",
        )


@router.get("")
async def list_automations(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None),
):
    """
    List all automations for an Instagram account.

    Args:
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client
        skip: Number of results to skip
        limit: Maximum number of results
        status_filter: Filter by status (active, paused, archived)

    Returns:
        dict: List of automations with pagination

    Status Codes:
        200: Success
        401: Unauthorized
        404: Account not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Verify account ownership using partition key for correct Cosmos DB routing
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )
        query = (
            "SELECT * FROM accounts "
            "WHERE accounts.id = @account_id AND accounts.user_id = @user_id"
        )
        accounts = []
        async for item in accounts_container.query_items(
            query=query,
            parameters=[
                {"name": "@account_id", "value": account_id},
                {"name": "@user_id", "value": user_id},
            ],
            partition_key=user_id,
        ):
            accounts.append(item)

        if not accounts:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not found or access denied",
            )

        # Build query
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        where_clause = "WHERE automations.account_id = @account_id"
        params = [{"name": "@account_id", "value": account_id}]

        if status_filter:
            where_clause += " AND automations.status = @status"
            params.append({"name": "@status", "value": status_filter})

        query = (
            f"SELECT * FROM automations {where_clause} "
            f"ORDER BY automations.created_at DESC "
            f"OFFSET {skip} LIMIT {limit}"
        )

        automations = []
        async for item in automations_container.query_items(
            query=query,
            parameters=params,
        ):
            automations.append(item)

        # Get total count
        count_query = f"SELECT VALUE COUNT(1) FROM automations {where_clause}"
        total_count = 0
        async for item in automations_container.query_items(
            query=count_query,
            parameters=params,
        ):
            total_count = item

        return {
            "automations": automations,
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing automations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list automations",
        )


@router.get("/{automation_id}")
async def get_automation(
    automation_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get details for a specific automation.

    Args:
        automation_id: Automation ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Automation details

    Status Codes:
        200: Success
        401: Unauthorized
        404: Automation not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        # Fetch automation
        query = "SELECT * FROM automations WHERE automations.id = @automation_id"
        automations = []
        async for item in automations_container.query_items(
            query=query,
            parameters=[{"name": "@automation_id", "value": automation_id}],
        ):
            automations.append(item)

        if not automations:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Automation not found",
            )

        automation = automations[0]

        # Verify ownership
        if automation.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return automation

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting automation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get automation",
        )


@router.put("/{automation_id}")
async def update_automation(
    automation_id: str,
    name: Optional[str] = None,
    trigger: Optional[Dict[str, Any]] = None,
    conditions: Optional[List[Dict[str, Any]]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Update an existing automation.

    Args:
        automation_id: Automation ID
        name: Updated automation name
        trigger: Updated trigger configuration
        conditions: Updated conditions list
        steps: Updated steps list
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Updated automation

    Status Codes:
        200: Success
        400: Invalid input
        401: Unauthorized
        404: Automation not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        # Fetch automation
        query = "SELECT * FROM automations WHERE automations.id = @automation_id"
        automations = []
        async for item in automations_container.query_items(
            query=query,
            parameters=[{"name": "@automation_id", "value": automation_id}],
        ):
            automations.append(item)

        if not automations:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Automation not found",
            )

        automation = automations[0]

        # Verify ownership
        if automation.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Update fields
        if name is not None:
            automation["name"] = name
        if trigger is not None:
            automation["trigger"] = trigger
            tr = trigger or {}
            tt_raw = tr.get("type") or "message_received"
            tt = tt_raw.lower().replace("-", "_") if isinstance(tt_raw, str) else "message_received"
            if tt in ("keyword",):
                tt = "dm_keyword"
            if tt == "message_received" and (tr.get("keywords") or []):
                automation["automation_type"] = "dm_keyword"
            else:
                automation["automation_type"] = tt
        if conditions is not None:
            automation["conditions"] = conditions
        if steps is not None:
            automation["steps"] = steps

        automation["updated_at"] = None  # Cosmos DB will set timestamp

        # Save changes
        await automations_container.replace_item(
            item=automation_id,
            body=automation,
        )

        return automation

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating automation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update automation",
        )


@router.patch("/{automation_id}/status")
async def update_automation_status(
    automation_id: str,
    status_value: str = Query(..., pattern="^(active|paused|archived)$"),
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Update automation status (activate, pause, or archive).

    Args:
        automation_id: Automation ID
        status_value: New status (active, paused, or archived)
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Updated automation

    Status Codes:
        200: Success
        400: Invalid status
        401: Unauthorized
        404: Automation not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        # Fetch automation
        query = "SELECT * FROM automations WHERE automations.id = @automation_id"
        automations = []
        async for item in automations_container.query_items(
            query=query,
            parameters=[{"name": "@automation_id", "value": automation_id}],
        ):
            automations.append(item)

        if not automations:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Automation not found",
            )

        automation = automations[0]

        # Verify ownership
        if automation.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Update status and enabled flag
        automation["status"] = status_value
        automation["enabled"] = status_value == "active"
        automation["updated_at"] = None

        # Save changes
        await automations_container.replace_item(
            item=automation_id,
            body=automation,
        )

        return automation

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating automation status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update automation status",
        )


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    automation_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Delete an automation.

    Args:
        automation_id: Automation ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Status Codes:
        204: Automation deleted successfully
        401: Unauthorized
        404: Automation not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        # Fetch automation
        query = "SELECT * FROM automations WHERE automations.id = @automation_id"
        automations = []
        async for item in automations_container.query_items(
            query=query,
            parameters=[{"name": "@automation_id", "value": automation_id}],
        ):
            automations.append(item)

        if not automations:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Automation not found",
            )

        automation = automations[0]

        # Verify ownership
        if automation.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Delete automation
        await automations_container.delete_item(
            item=automation_id,
            partition_key=automation.get("user_id"),
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting automation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete automation",
        )
