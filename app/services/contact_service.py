"""Contact management service for DM automation."""
import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.core.config import dm_settings
from app.db.cosmos_db import CosmosDBClient
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class ContactService:
    """
    Manages contact data for DM automation.

    Tracks:
    - Contact profiles (IG username, name, etc.)
    - Interaction history (messages sent, engagement)
    - Tags (user-defined categorization)
    - Messaging window (when we can send follow-up messages)
    - Human handoff status (for escalation to human agent)
    """

    def __init__(self, cosmos_client: Optional[CosmosDBClient] = None, redis_conn=None):
        """Initialize contact service."""
        self.cosmos_client = cosmos_client or CosmosDBClient()
        self.redis = redis_conn or redis_client

    def _get_contact_cache_key(self, account_id: str, contact_id: str) -> str:
        """Build Redis cache key for contact."""
        return f"dm:contact:{account_id}:{contact_id}"

    async def get_or_create_contact(
        self,
        account_id: str,
        ig_user_id: str,
        ig_username: str,
        ig_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get existing contact or create new one.

        Args:
            account_id: Instagram account ID
            ig_user_id: IG user ID
            ig_username: IG username
            ig_name: Display name (optional)

        Returns:
            Contact document dict
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            # Try to find existing contact
            query = """
                SELECT * FROM c
                WHERE c.account_id = @account_id
                AND c.ig_user_id = @ig_user_id
            """
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@account_id", "value": account_id},
                    {"name": "@ig_user_id", "value": ig_user_id}
                ]
            ))

            if items:
                contact = items[0]
                logger.debug(f"Found existing contact {contact['id']}")
                return contact

            # Create new contact
            contact_id = str(uuid.uuid4())
            now = datetime.utcnow()

            contact = {
                "id": contact_id,
                "account_id": account_id,
                "ig_user_id": ig_user_id,
                "ig_username": ig_username,
                "ig_name": ig_name or ig_username,
                "tags": [],
                "interaction_count": 0,
                "last_message_sent_at": None,
                "last_message_received_at": None,
                "messaging_window_expires_at": None,
                "is_human_handoff": False,
                "human_handoff_reason": None,
                "human_handoff_at": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "metadata": {}
            }

            logger.debug(f"Creating new contact {contact_id} for {ig_username}")
            container.create_item(body=contact)

            return contact

        except Exception as e:
            logger.error(f"Error getting or creating contact: {str(e)}")
            raise

    async def update_contact_interaction(
        self,
        account_id: str,
        contact_id: str,
        interaction_type: str = "message_sent"
    ) -> bool:
        """
        Update contact interaction record.

        Args:
            account_id: Instagram account ID
            contact_id: Contact ID
            interaction_type: Type of interaction (message_sent, message_received, engaged)

        Returns:
            True if updated successfully
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            query = "SELECT * FROM c WHERE c.id = @contact_id AND c.account_id = @account_id"
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@contact_id", "value": contact_id},
                    {"name": "@account_id", "value": account_id}
                ]
            ))

            if not items:
                logger.error(f"Contact {contact_id} not found")
                return False

            contact = items[0]
            now = datetime.utcnow()

            # Update interaction count
            contact["interaction_count"] = contact.get("interaction_count", 0) + 1

            # Update last interaction timestamp based on type
            if interaction_type == "message_sent":
                contact["last_message_sent_at"] = now.isoformat()
            elif interaction_type == "message_received":
                contact["last_message_received_at"] = now.isoformat()
                # Extend messaging window when user responds
                contact["messaging_window_expires_at"] = (
                    now + timedelta(hours=dm_settings.MESSAGING_WINDOW_HOURS)
                ).isoformat()

            contact["updated_at"] = now.isoformat()

            logger.debug(f"Updated interaction for contact {contact_id}: {interaction_type}")
            container.replace_item(item=contact_id, body=contact, partition_key=account_id)

            # Invalidate cache
            self._invalidate_contact_cache(account_id, contact_id)

            return True

        except Exception as e:
            logger.error(f"Error updating contact interaction: {str(e)}")
            return False

    async def add_tag(self, account_id: str, contact_id: str, tag: str) -> bool:
        """
        Add a tag to a contact.

        Args:
            account_id: Instagram account ID
            contact_id: Contact ID
            tag: Tag to add

        Returns:
            True if tag added successfully
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            query = "SELECT * FROM c WHERE c.id = @contact_id AND c.account_id = @account_id"
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@contact_id", "value": contact_id},
                    {"name": "@account_id", "value": account_id}
                ]
            ))

            if not items:
                logger.error(f"Contact {contact_id} not found")
                return False

            contact = items[0]
            tags = contact.get("tags", [])

            if tag not in tags:
                tags.append(tag)
                contact["tags"] = tags
                contact["updated_at"] = datetime.utcnow().isoformat()

                logger.debug(f"Added tag '{tag}' to contact {contact_id}")
                container.replace_item(item=contact_id, body=contact, partition_key=account_id)

                self._invalidate_contact_cache(account_id, contact_id)

            return True

        except Exception as e:
            logger.error(f"Error adding tag to contact: {str(e)}")
            return False

    async def remove_tag(self, account_id: str, contact_id: str, tag: str) -> bool:
        """
        Remove a tag from a contact.

        Args:
            account_id: Instagram account ID
            contact_id: Contact ID
            tag: Tag to remove

        Returns:
            True if tag removed successfully
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            query = "SELECT * FROM c WHERE c.id = @contact_id AND c.account_id = @account_id"
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@contact_id", "value": contact_id},
                    {"name": "@account_id", "value": account_id}
                ]
            ))

            if not items:
                logger.error(f"Contact {contact_id} not found")
                return False

            contact = items[0]
            tags = contact.get("tags", [])

            if tag in tags:
                tags.remove(tag)
                contact["tags"] = tags
                contact["updated_at"] = datetime.utcnow().isoformat()

                logger.debug(f"Removed tag '{tag}' from contact {contact_id}")
                container.replace_item(item=contact_id, body=contact, partition_key=account_id)

                self._invalidate_contact_cache(account_id, contact_id)

            return True

        except Exception as e:
            logger.error(f"Error removing tag from contact: {str(e)}")
            return False

    async def refresh_messaging_window(
        self,
        account_id: str,
        contact_id: str
    ) -> bool:
        """
        Refresh (extend) the messaging window for a contact.

        Messaging window is the time period after the last message from the user
        during which we can send follow-up messages.

        Args:
            account_id: Instagram account ID
            contact_id: Contact ID

        Returns:
            True if messaging window refreshed
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            query = "SELECT * FROM c WHERE c.id = @contact_id AND c.account_id = @account_id"
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@contact_id", "value": contact_id},
                    {"name": "@account_id", "value": account_id}
                ]
            ))

            if not items:
                logger.error(f"Contact {contact_id} not found")
                return False

            contact = items[0]
            now = datetime.utcnow()
            expires_at = now + timedelta(hours=dm_settings.MESSAGING_WINDOW_HOURS)

            contact["messaging_window_expires_at"] = expires_at.isoformat()
            contact["updated_at"] = now.isoformat()

            logger.debug(
                f"Refreshed messaging window for contact {contact_id}, "
                f"expires at {expires_at}"
            )
            container.replace_item(item=contact_id, body=contact, partition_key=account_id)

            self._invalidate_contact_cache(account_id, contact_id)

            return True

        except Exception as e:
            logger.error(f"Error refreshing messaging window: {str(e)}")
            return False

    async def set_human_handoff(
        self,
        account_id: str,
        contact_id: str,
        reason: str
    ) -> bool:
        """
        Mark a contact for human handoff (escalation to human agent).

        Args:
            account_id: Instagram account ID
            contact_id: Contact ID
            reason: Reason for handoff

        Returns:
            True if handoff set successfully
        """
        try:
            container = self.cosmos_client.get_container_client(
                dm_settings.DM_CONTACTS_CONTAINER
            )

            query = "SELECT * FROM c WHERE c.id = @contact_id AND c.account_id = @account_id"
            items = list(container.query_items(
                query=query,
                parameters=[
                    {"name": "@contact_id", "value": contact_id},
                    {"name": "@account_id", "value": account_id}
                ]
            ))

            if not items:
                logger.error(f"Contact {contact_id} not found")
                return False

            contact = items[0]
            now = datetime.utcnow()

            contact["is_human_handoff"] = True
            contact["human_handoff_reason"] = reason
            contact["human_handoff_at"] = now.isoformat()
            contact["updated_at"] = now.isoformat()

            logger.info(f"Set human handoff for contact {contact_id}: {reason}")
            container.replace_item(item=contact_id, body=contact, partition_key=account_id)

            self._invalidate_contact_cache(account_id, contact_id)

            return True

        except Exception as e:
            logger.error(f"Error setting human handoff: {str(e)}")
            return False

    def _invalidate_contact_cache(self, account_id: str, contact_id: str) -> None:
        """Invalidate Redis cache for a contact."""
        try:
            cache_key = self._get_contact_cache_key(account_id, contact_id)
            self.redis.delete(cache_key)
            logger.debug(f"Invalidated cache for contact {contact_id}")
        except Exception as e:
            logger.error(f"Error invalidating contact cache: {str(e)}")
