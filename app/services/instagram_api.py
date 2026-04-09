"""Instagram Graph API service for DM automation."""
import asyncio
import logging
from typing import Dict, Any, Optional, List
import httpx
from datetime import datetime

from app.core.config import dm_settings
from app.services.token_manager import TokenManager
from app.services.rate_limiter import RateLimiter
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


class InstagramAPIError(Exception):
    """Custom exception for Instagram API errors."""
    pass


class RateLimitExceeded(InstagramAPIError):
    """Raised when API rate limit is exceeded."""
    pass


class TokenExpired(InstagramAPIError):
    """Raised when access token has expired."""
    pass


class InstagramAPI:
    """
    Instagram Graph API client for DM automation.

    Handles:
    - Sending direct messages (text, generic template, carousel)
    - Checking follower status
    - Fetching user profiles
    - Managing webhook subscriptions
    - Token decryption and error handling
    """

    def __init__(
        self,
        token_manager: Optional[TokenManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
        redis_conn=None
    ):
        """Initialize Instagram API client."""
        self.token_manager = token_manager or TokenManager()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.redis = redis_conn or redis_client
        self.api_base_url = dm_settings.INSTAGRAM_API_BASE_URL
        self.api_version = dm_settings.INSTAGRAM_API_VERSION

    async def send_dm(
        self,
        account_id: str,
        recipient_id: str,
        message_payload: Dict[str, Any],
        comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a direct message via Instagram API.

        Supports:
        - text: Simple text message
        - generic_template: Card with buttons
        - carousel: Multiple cards with buttons

        For comment-triggered automations, pass comment_id to send the DM
        as a reply to the comment. Instagram requires:
            recipient: { comment_id: "<COMMENT_ID>" }
        instead of:
            recipient: { id: "<USER_ID>" }

        Args:
            account_id: Instagram account ID (business account)
            recipient_id: Recipient's IG user ID (used for regular DMs)
            message_payload: Message payload dict with 'type' and 'content'
            comment_id: If set, sends DM as reply to this comment (for comment automations)

        Returns:
            API response with message_id

        Raises:
            InstagramAPIError: If API call fails
            RateLimitExceeded: If rate limit exceeded
            TokenExpired: If access token expired
        """
        try:
            logger.info(f"Sending DM to {recipient_id} from account {account_id}")

            account = self.token_manager.get_account_document(account_id)
            encrypted = account.get("access_token")
            if not encrypted:
                logger.error(f"No access token found for account {account_id}")
                raise ValueError(f"No access token for account {account_id}")
            access_token = self.token_manager.decrypt_token(encrypted)
            graph_user_id = self.token_manager.graph_user_id_from_document(
                account, account_id
            )

            # Check rate limit
            if not self.rate_limiter.check_rate_limit(account_id):
                logger.warning(f"Rate limit exceeded for account {account_id}")
                raise RateLimitExceeded(f"Account {account_id} has exceeded DM rate limit")

            # Graph API path uses IG user id, not internal instagram_… document id
            url = f"{self.api_base_url}/{self.api_version}/{graph_user_id}/messages"

            # Build request body
            request_body = self._build_send_message_request(
                recipient_id, message_payload, comment_id=comment_id
            )

            # Make API call
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=request_body,
                    params={"access_token": access_token}
                )

                # Handle different response codes
                if response.status_code == 429:
                    logger.error(f"Rate limit hit from Instagram API for account {account_id}")
                    raise RateLimitExceeded("Instagram API rate limit exceeded")

                if response.status_code == 401:
                    logger.error(f"Unauthorized - token expired for account {account_id}")
                    raise TokenExpired(f"Access token expired for account {account_id}")

                if response.status_code not in (200, 201):
                    error_text = response.text
                    logger.error(
                        f"Instagram API error for {account_id}: "
                        f"status={response.status_code}, response={error_text}"
                    )
                    raise InstagramAPIError(
                        f"Instagram API returned {response.status_code}: {error_text}"
                    )

                result = response.json()
                message_id = result.get("message_id")

                logger.info(f"Message sent successfully - id={message_id}, recipient={recipient_id}")

                # Record in rate limiter after successful send
                self.rate_limiter.record_send(account_id)

                return {
                    "success": True,
                    "message_id": message_id,
                    "recipient_id": recipient_id,
                    "timestamp": datetime.utcnow().isoformat()
                }

        except (RateLimitExceeded, TokenExpired, InstagramAPIError):
            raise
        except Exception as e:
            logger.error(f"Error sending DM: {str(e)}")
            raise InstagramAPIError(f"Failed to send DM: {str(e)}")

    def send_dm_sync(
        self,
        account_id: str,
        recipient_id: str,
        message_payload: Dict[str, Any],
        comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run async send_dm from synchronous worker code (webhooks, Celery).

        Uses asyncio.run(); do not call from inside a running event loop.
        """
        return asyncio.run(
            self.send_dm(
                account_id,
                recipient_id,
                message_payload,
                comment_id=comment_id,
            )
        )

    def _build_send_message_request(
        self,
        recipient_id: str,
        message_payload: Dict[str, Any],
        comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build request body for send message API call.

        For comment-triggered DMs, Instagram requires:
            recipient: { comment_id: "<COMMENT_ID>" }
        For regular DMs:
            recipient: { id: "<USER_ID>" }
        """
        payload_type = message_payload.get("type", "text").lower()
        content = message_payload.get("content", {})

        # Comment-triggered DMs use comment_id as recipient (Instagram API requirement)
        if comment_id:
            recipient = {"comment_id": comment_id}
        else:
            recipient = {"id": recipient_id}

        request = {
            "recipient": recipient,
            "messaging_type": "MESSAGE_TYPE_RESPONSE"
        }

        if payload_type == "text":
            request["message"] = {
                "text": content.get("text", "")
            }
        elif payload_type in ("generic", "carousel"):
            # Build generic template payload
            elements = content.get("elements", [content])  # Single element if not carousel

            request["message"] = {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": elements
                    }
                }
            }

        return request

    async def check_follow_status(
        self,
        account_id: str,
        ig_user_id: str
    ) -> bool:
        """
        Check if a user follows the Instagram account.

        Uses the followers edge with fields parameter.

        Args:
            account_id: Instagram account ID
            ig_user_id: User ID to check

        Returns:
            True if user follows account, False otherwise

        Raises:
            InstagramAPIError: If API call fails
        """
        try:
            logger.debug(f"Checking follow status for user {ig_user_id} on account {account_id}")

            account = self.token_manager.get_account_document(account_id)
            encrypted = account.get("access_token")
            if not encrypted:
                logger.error(f"No access token found for account {account_id}")
                raise ValueError(f"No access token for account {account_id}")
            access_token = self.token_manager.decrypt_token(encrypted)
            graph_user_id = self.token_manager.graph_user_id_from_document(
                account, account_id
            )

            # Query the followers edge to check if user is in the list
            # Note: This requires the user to have granted permission and the app to have access
            url = f"{self.api_base_url}/{self.api_version}/{graph_user_id}/followers"

            params = {
                "access_token": access_token,
                "fields": f"username,id"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 401:
                    raise TokenExpired(f"Token expired for account {account_id}")

                if response.status_code != 200:
                    logger.error(
                        f"Error checking followers for {account_id}: "
                        f"status={response.status_code}"
                    )
                    return False

                data = response.json()
                followers = data.get("data", [])

                # Check if user is in follower list
                is_follower = any(f.get("id") == ig_user_id for f in followers)

                logger.debug(
                    f"Follow status for user {ig_user_id}: {is_follower}"
                )

                return is_follower

        except TokenExpired:
            raise
        except Exception as e:
            logger.error(f"Error checking follow status: {str(e)}")
            raise InstagramAPIError(f"Failed to check follow status: {str(e)}")

    async def get_user_profile(
        self,
        access_token: str,
        ig_user_id: str
    ) -> Dict[str, Any]:
        """
        Fetch Instagram user profile information.

        Args:
            access_token: Access token (decrypted)
            ig_user_id: IG user ID to fetch

        Returns:
            User profile data (username, name, biography, profile_pic_url, etc.)

        Raises:
            InstagramAPIError: If API call fails
        """
        try:
            logger.debug(f"Fetching profile for user {ig_user_id}")

            url = f"{self.api_base_url}/{self.api_version}/{ig_user_id}"

            fields = [
                "id",
                "username",
                "name",
                "biography",
                "profile_pic_url",
                "followers_count",
                "follows_count",
                "media_count",
                "ig_id"
            ]

            params = {
                "access_token": access_token,
                "fields": ",".join(fields)
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 401:
                    raise TokenExpired("Access token expired")

                if response.status_code != 200:
                    logger.error(
                        f"Error fetching profile for {ig_user_id}: "
                        f"status={response.status_code}"
                    )
                    raise InstagramAPIError(
                        f"Failed to fetch profile: {response.status_code}"
                    )

                profile = response.json()
                logger.debug(f"Successfully fetched profile for {ig_user_id}")

                return profile

        except TokenExpired:
            raise
        except Exception as e:
            logger.error(f"Error getting user profile: {str(e)}")
            raise InstagramAPIError(f"Failed to get user profile: {str(e)}")

    async def subscribe_webhooks(
        self,
        access_token: str,
        page_id: str,
        fields: List[str]
    ) -> bool:
        """
        Subscribe to Instagram webhook events.

        Args:
            access_token: Access token (decrypted)
            page_id: Facebook page ID
            fields: List of webhook fields to subscribe to (e.g., ['messages', 'message_status'])

        Returns:
            True if subscription successful

        Raises:
            InstagramAPIError: If subscription fails
        """
        try:
            logger.info(f"Subscribing to webhooks for page {page_id}: fields={fields}")

            url = f"{self.api_base_url}/{self.api_version}/{page_id}/subscribed_apps"

            data = {
                "access_token": access_token,
                "subscribed_fields": ",".join(fields)
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, data=data)

                if response.status_code == 401:
                    raise TokenExpired("Access token expired")

                if response.status_code not in (200, 201):
                    error_text = response.text
                    logger.error(
                        f"Webhook subscription failed for page {page_id}: "
                        f"status={response.status_code}, response={error_text}"
                    )
                    raise InstagramAPIError(f"Webhook subscription failed: {error_text}")

                logger.info(f"Successfully subscribed to webhooks for page {page_id}")
                return True

        except TokenExpired:
            raise
        except Exception as e:
            logger.error(f"Error subscribing to webhooks: {str(e)}")
            raise InstagramAPIError(f"Failed to subscribe to webhooks: {str(e)}")

    async def unsubscribe_webhooks(
        self,
        access_token: str,
        page_id: str
    ) -> bool:
        """
        Unsubscribe from Instagram webhook events.

        Args:
            access_token: Access token (decrypted)
            page_id: Facebook page ID

        Returns:
            True if unsubscription successful

        Raises:
            InstagramAPIError: If unsubscription fails
        """
        try:
            logger.info(f"Unsubscribing from webhooks for page {page_id}")

            url = f"{self.api_base_url}/{self.api_version}/{page_id}/subscribed_apps"

            params = {
                "access_token": access_token
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(url, params=params)

                if response.status_code == 401:
                    raise TokenExpired("Access token expired")

                if response.status_code not in (200, 204):
                    error_text = response.text
                    logger.error(
                        f"Webhook unsubscription failed for page {page_id}: "
                        f"status={response.status_code}, response={error_text}"
                    )
                    raise InstagramAPIError(f"Webhook unsubscription failed: {error_text}")

                logger.info(f"Successfully unsubscribed from webhooks for page {page_id}")
                return True

        except TokenExpired:
            raise
        except Exception as e:
            logger.error(f"Error unsubscribing from webhooks: {str(e)}")
            raise InstagramAPIError(f"Failed to unsubscribe from webhooks: {str(e)}")


# Global singleton instance
instagram_api = InstagramAPI()
