"""Contact management routes for DM contacts."""
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Depends, Query

from app.api.deps import (
    get_current_user,
    get_cosmos_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["Contacts"])

CONTACTS_CONTAINER = "dm_contacts"
MESSAGES_CONTAINER = "dm_messages"
INSTAGRAM_TOKEN_CONTAINER = "instagram_accounts"


@router.get("")
async def list_contacts(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    tags: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """
    List contacts for an Instagram account with pagination, filtering, and search.

    Args:
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client
        skip: Number of results to skip
        limit: Maximum number of results
        tags: Comma-separated tag filters
        search: Search query for contact name, username, or ID

    Returns:
        dict: List of contacts with metadata

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

        # Build query
        contacts_container = await cosmos_client.get_async_container_client(
            CONTACTS_CONTAINER
        )

        where_clause = "WHERE contacts.account_id = @account_id"
        params = [{"name": "@account_id", "value": account_id}]

        # Add tag filter
        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            where_clause += " AND ARRAY_CONTAINS(contacts.tags, @tag_filter)"
            params.append({"name": "@tag_filter", "value": tag_list[0]})

        # Add search filter
        if search:
            where_clause += (
                " AND (CONTAINS(LOWER(contacts.name), LOWER(@search)) "
                "OR CONTAINS(LOWER(contacts.username), LOWER(@search)) "
                "OR CONTAINS(LOWER(contacts.ig_user_id), LOWER(@search)))"
            )
            params.append({"name": "@search", "value": search})

        query = (
            f"SELECT * FROM contacts {where_clause} "
            f"ORDER BY contacts.last_message_at DESC "
            f"OFFSET {skip} LIMIT {limit}"
        )

        contacts = []
        async for item in contacts_container.query_items(
            query=query,
            parameters=params,
        ):
            contacts.append(item)

        # Get total count
        count_query = f"SELECT VALUE COUNT(1) FROM contacts {where_clause}"
        total_count = 0
        async for item in contacts_container.query_items(
            query=count_query,
            parameters=params,
        ):
            total_count = item

        return {
            "contacts": contacts,
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing contacts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list contacts",
        )


@router.get("/{contact_id}")
async def get_contact(
    contact_id: str,
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Get details for a specific contact.

    Args:
        contact_id: Contact ID
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Contact details

    Status Codes:
        200: Success
        401: Unauthorized
        404: Contact not found
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

        # Fetch contact
        contacts_container = await cosmos_client.get_async_container_client(
            CONTACTS_CONTAINER
        )
        query = (
            "SELECT * FROM contacts "
            "WHERE contacts.id = @contact_id AND contacts.account_id = @account_id"
        )
        contacts = []
        async for item in contacts_container.query_items(
            query=query,
            parameters=[
                {"name": "@contact_id", "value": contact_id},
                {"name": "@account_id", "value": account_id},
            ],
        ):
            contacts.append(item)

        if not contacts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        return contacts[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting contact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get contact",
        )


@router.get("/{contact_id}/messages")
async def get_contact_messages(
    contact_id: str,
    account_id: str,
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get message history for a contact.

    Args:
        contact_id: Contact ID
        account_id: Instagram account ID
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client
        skip: Number of messages to skip
        limit: Maximum number of messages to return

    Returns:
        dict: List of messages with pagination

    Status Codes:
        200: Success
        401: Unauthorized
        404: Contact not found
        500: Server error
    """
    try:
        user_id = current_user.get("sub")

        # Verify account and contact ownership
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

        # Fetch messages
        messages_container = await cosmos_client.get_async_container_client(
            MESSAGES_CONTAINER
        )
        query = (
            "SELECT * FROM messages "
            "WHERE messages.contact_id = @contact_id "
            "AND messages.account_id = @account_id "
            "ORDER BY messages.timestamp DESC "
            f"OFFSET {skip} LIMIT {limit}"
        )

        messages = []
        async for item in messages_container.query_items(
            query=query,
            parameters=[
                {"name": "@contact_id", "value": contact_id},
                {"name": "@account_id", "value": account_id},
            ],
        ):
            messages.append(item)

        # Get total count
        count_query = (
            "SELECT VALUE COUNT(1) FROM messages "
            "WHERE messages.contact_id = @contact_id "
            "AND messages.account_id = @account_id"
        )
        total_count = 0
        async for item in messages_container.query_items(
            query=count_query,
            parameters=[
                {"name": "@contact_id", "value": contact_id},
                {"name": "@account_id", "value": account_id},
            ],
        ):
            total_count = item

        return {
            "messages": messages,
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get messages",
        )


@router.patch("/{contact_id}/tags")
async def update_contact_tags(
    contact_id: str,
    account_id: str,
    add_tags: Optional[List[str]] = Query(None),
    remove_tags: Optional[List[str]] = Query(None),
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Add or remove tags from a contact.

    Args:
        contact_id: Contact ID
        account_id: Instagram account ID
        add_tags: List of tags to add
        remove_tags: List of tags to remove
        current_user: Current authenticated user
        cosmos_client: Cosmos DB client

    Returns:
        dict: Updated contact

    Status Codes:
        200: Success
        400: Invalid input
        401: Unauthorized
        404: Contact not found
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

        # Fetch contact
        contacts_container = await cosmos_client.get_async_container_client(
            CONTACTS_CONTAINER
        )
        query = (
            "SELECT * FROM contacts "
            "WHERE contacts.id = @contact_id AND contacts.account_id = @account_id"
        )
        contacts = []
        async for item in contacts_container.query_items(
            query=query,
            parameters=[
                {"name": "@contact_id", "value": contact_id},
                {"name": "@account_id", "value": account_id},
            ],
        ):
            contacts.append(item)

        if not contacts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found",
            )

        contact = contacts[0]
        current_tags = set(contact.get("tags", []))

        # Update tags
        if add_tags:
            current_tags.update(add_tags)

        if remove_tags:
            current_tags.difference_update(remove_tags)

        contact["tags"] = list(current_tags)
        contact["updated_at"] = None

        # Save changes
        await contacts_container.replace_item(
            item=contact_id,
            body=contact,
        )

        return contact

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating contact tags: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update contact tags",
        )
