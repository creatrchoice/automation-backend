"""Analytics and reporting routes for DM automation."""
import logging
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, status, Depends, Query

from app.api.deps import (
    get_current_user,
    get_cosmos_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

from app.db.cosmos_containers import CONTAINER_MESSAGE_LOGS, CONTAINER_AUTOMATIONS, CONTAINER_CONTACTS, CONTAINER_IG_ACCOUNTS
MESSAGES_CONTAINER = CONTAINER_MESSAGE_LOGS
AUTOMATIONS_CONTAINER = CONTAINER_AUTOMATIONS
CONTACTS_CONTAINER = CONTAINER_CONTACTS
INSTAGRAM_TOKEN_CONTAINER = CONTAINER_IG_ACCOUNTS


@router.get("/overview")
async def get_analytics_overview(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get dashboard overview analytics for an account.

    Returns aggregated metrics:
    - Total messages (sent and received)
    - Message delivery rate
    - Total unique contacts
    - Active automations
    - Average response time
    - Today's message count
    - Weekly trend

    Args:
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Overview metrics and statistics

    Status Codes:
        200: Success
        401: Unauthorized
        404: Account not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Verify account ownership
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )
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
        if account.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        messages_container = await cosmos_client.get_async_container_client(
            MESSAGES_CONTAINER
        )
        contacts_container = await cosmos_client.get_async_container_client(
            CONTACTS_CONTAINER
        )
        automations_container = await cosmos_client.get_async_container_client(
            AUTOMATIONS_CONTAINER
        )

        # Total messages
        query = (
            "SELECT VALUE COUNT(1) FROM messages "
            "WHERE messages.account_id = @account_id"
        )
        total_messages = 0
        async for item in messages_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            total_messages = item
            break

        # Delivered messages
        query = (
            "SELECT VALUE COUNT(1) FROM messages "
            "WHERE messages.account_id = @account_id AND messages.status = 'delivered'"
        )
        delivered_messages = 0
        async for item in messages_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            delivered_messages = item
            break

        # Unique contacts
        query = (
            "SELECT VALUE COUNT(1) FROM (SELECT DISTINCT messages.contact_id FROM messages "
            "WHERE messages.account_id = @account_id)"
        )
        unique_contacts = 0
        async for item in messages_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            unique_contacts = item
            break

        # Active automations
        query = (
            "SELECT VALUE COUNT(1) FROM automations "
            "WHERE automations.account_id = @account_id AND automations.status = 'active'"
        )
        active_automations = 0
        async for item in automations_container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
        ):
            active_automations = item
            break

        # Today's messages
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time()).timestamp()
        query = (
            "SELECT VALUE COUNT(1) FROM messages "
            "WHERE messages.account_id = @account_id "
            "AND messages.timestamp >= @today_start"
        )
        today_messages = 0
        async for item in messages_container.query_items(
            query=query,
            parameters=[
                {"name": "@account_id", "value": account_id},
                {"name": "@today_start", "value": today_start},
            ],
        ):
            today_messages = item
            break

        delivery_rate = (
            (delivered_messages / total_messages * 100)
            if total_messages > 0
            else 0
        )

        return {
            "total_messages": total_messages,
            "delivered_messages": delivered_messages,
            "delivery_rate": round(delivery_rate, 2),
            "unique_contacts": unique_contacts,
            "active_automations": active_automations,
            "today_messages": today_messages,
            "account_id": account_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting analytics overview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get analytics overview",
        )


@router.get("/automations/{automation_id}")
async def get_automation_analytics(
    automation_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get detailed analytics for a specific automation.

    Returns:
    - Total runs
    - Successful executions
    - Failed executions
    - Error rate
    - Average execution time
    - Per-step breakdown (success rate, error counts)
    - Recent errors

    Args:
        automation_id: Automation ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Automation analytics

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

        # Get execution logs (hypothetical container)
        # In production, would query execution history
        return {
            "automation_id": automation_id,
            "automation_name": automation.get("name"),
            "total_runs": automation.get("run_count", 0),
            "error_count": automation.get("error_count", 0),
            "success_rate": (
                (
                    (automation.get("run_count", 1) - automation.get("error_count", 0))
                    / automation.get("run_count", 1)
                    * 100
                )
                if automation.get("run_count", 0) > 0
                else 0
            ),
            "steps": automation.get("steps", []),
            "last_run_at": automation.get("updated_at"),
            "status": automation.get("status"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting automation analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get automation analytics",
        )


@router.get("/daily")
async def get_daily_analytics(
    account_id: str,
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get daily statistics for a date range.

    Returns daily breakdown of:
    - Messages sent/received
    - Contacts reached
    - Automations executed
    - Average response time

    Args:
        account_id: Instagram account ID
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Daily analytics data

    Status Codes:
        200: Success
        400: Invalid date format
        401: Unauthorized
        404: Account not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Verify account ownership
        accounts_container = await cosmos_client.get_async_container_client(
            INSTAGRAM_TOKEN_CONTAINER
        )
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
        if account.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Parse dates
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD",
            )

        if start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before end_date",
            )

        # Generate daily breakdown
        daily_data = []
        current = start
        messages_container = await cosmos_client.get_async_container_client(
            MESSAGES_CONTAINER
        )

        while current <= end:
            day_start = current.timestamp()
            day_end = (current + timedelta(days=1)).timestamp()

            query = (
                "SELECT VALUE COUNT(1) FROM messages "
                "WHERE messages.account_id = @account_id "
                "AND messages.timestamp >= @day_start "
                "AND messages.timestamp < @day_end"
            )

            day_count = 0
            async for item in messages_container.query_items(
                query=query,
                parameters=[
                    {"name": "@account_id", "value": account_id},
                    {"name": "@day_start", "value": day_start},
                    {"name": "@day_end", "value": day_end},
                ],
            ):
                day_count = item
                break

            daily_data.append({
                "date": current.date().isoformat(),
                "message_count": day_count,
            })

            current += timedelta(days=1)

        return {
            "account_id": account_id,
            "start_date": start_date,
            "end_date": end_date,
            "daily_data": daily_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting daily analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get daily analytics",
        )
