"""Instagram Graph API service for DM automation."""
import asyncio
import json
import logging
import threading
from typing import Dict, Any, Optional, List
import httpx
from datetime import datetime

from app.core.config import dm_settings
from app.services.token_manager import TokenManager
from app.core.security import SecurityError
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

    @staticmethod
    def _looks_like_encrypted_token(token: str) -> bool:
        """Heuristic for Fernet-style encrypted tokens."""
        return isinstance(token, str) and token.startswith("gAAAA")

    def _get_account_access_token(
        self, account_id: str, account: Dict[str, Any]
    ) -> str:
        """Return decrypted token when encrypted, else plaintext fallback."""
        raw_token = account.get("access_token")
        if not raw_token:
            logger.error(f"No access token found for account {account_id}")
            raise ValueError(f"No access token for account {account_id}")

        if not self._looks_like_encrypted_token(raw_token):
            logger.warning(
                "Access token for account %s is not encrypted; using plaintext fallback.",
                account_id,
            )
            return raw_token

        return self.token_manager.decrypt_token(raw_token)

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

        For **text** only, you may set ``comment_id`` to send a private reply on the
        comment thread. **Generic** and **carousel** always use
        ``recipient: { "id": recipient_id }``; ``comment_id`` is ignored for those.

        Args:
            account_id: Instagram account ID (business account)
            recipient_id: Recipient's IG user ID (used for regular DMs)
            message_payload: Message payload dict with 'type' and 'content'
            comment_id: Text-only: private comment reply. Ignored for templates.

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
            access_token = self._get_account_access_token(account_id, account)
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
            logger.info(
                "Instagram outbound message payload account_id=%s graph_user_id=%s payload=%s",
                account_id,
                graph_user_id,
                json.dumps(
                    self._sanitize_request_for_logging(request_body),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            )

            # Make API call with retries for transient 5xx failures.
            max_attempts = 3
            response = None
            for attempt in range(1, max_attempts + 1):
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        url,
                        json=request_body,
                        params={"access_token": access_token}
                    )
                if response.status_code < 500 or attempt == max_attempts:
                    break
                wait_seconds = attempt
                logger.warning(
                    "Instagram API transient error for %s (status=%s, attempt=%s/%s), retrying in %ss",
                    account_id,
                    response.status_code,
                    attempt,
                    max_attempts,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)

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
                    "Instagram API error account_id=%s status=%s response=%s payload=%s",
                    account_id,
                    response.status_code,
                    error_text,
                    json.dumps(
                        self._sanitize_request_for_logging(request_body),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
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
        except ValueError:
            # e.g. account document missing; keep message clear for API callers and scripts
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

        If called while an event loop is already running (e.g. inside FastAPI
        request handling), run the coroutine in a dedicated thread to avoid
        nested-event-loop errors.
        """
        coroutine = self.send_dm(
            account_id,
            recipient_id,
            message_payload,
            comment_id=comment_id,
        )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Normal sync context with no active event loop.
            return asyncio.run(coroutine)

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result_holder["value"] = asyncio.run(coroutine)
            except BaseException as exc:
                error_holder["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if "error" in error_holder:
            raise error_holder["error"]

        return result_holder.get("value", {})

    async def reply_to_instagram_comment(
        self,
        account_id: str,
        comment_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Post a public reply under an existing Instagram comment.

        See Meta: POST /{ig-comment-id}/replies?message=...

        Args:
            account_id: Internal or IG-linked account id (for token lookup)
            comment_id: Instagram comment id to reply to
            message: Public reply text

        Returns:
            API JSON (typically includes id of the new reply)
        """
        if not (comment_id and message and str(message).strip()):
            raise ValueError("comment_id and non-empty message are required")

        try:
            logger.info(
                "Posting public reply to comment %s for account %s",
                comment_id,
                account_id,
            )
            account = self.token_manager.get_account_document(account_id)
            access_token = self._get_account_access_token(account_id, account)

            url = f"{self.api_base_url}/{self.api_version}/{comment_id}/replies"
            text = str(message).strip()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    params={
                        "message": text,
                        "access_token": access_token,
                    },
                )

            if response.status_code == 401:
                raise TokenExpired(f"Access token expired for account {account_id}")
            if response.status_code not in (200, 201):
                error_text = response.text
                logger.error(
                    "Instagram comment reply error for %s: status=%s body=%s",
                    account_id,
                    response.status_code,
                    error_text,
                )
                raise InstagramAPIError(
                    f"Instagram API returned {response.status_code}: {error_text}"
                )

            result = response.json()
            new_id = result.get("id")
            logger.info(
                "Public comment reply posted: comment_id=%s reply_id=%s",
                comment_id,
                new_id,
            )
            return {
                "success": True,
                "id": new_id,
                "comment_id": comment_id,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except (TokenExpired, InstagramAPIError):
            raise
        except Exception as e:
            logger.error("Error replying to Instagram comment: %s", e)
            raise InstagramAPIError(f"Failed to reply to comment: {e}") from e

    def reply_to_instagram_comment_sync(
        self,
        account_id: str,
        comment_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """Sync wrapper; safe when called from a running asyncio event loop."""
        coroutine = self.reply_to_instagram_comment(
            account_id, comment_id, message
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        result_holder: Dict[str, Any] = {}
        error_holder: Dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result_holder["value"] = asyncio.run(coroutine)
            except BaseException as exc:
                error_holder["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if "error" in error_holder:
            raise error_holder["error"]

        return result_holder.get("value", {})

    def _build_send_message_request(
        self,
        recipient_id: str,
        message_payload: Dict[str, Any],
        comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build request body for send message API call.

        Prefer ``recipient: { comment_id }`` when provided. Falls back to
        ``recipient: { id }`` when no comment id is available.
        """
        payload_type = message_payload.get("type", "text").lower()
        content = message_payload.get("content", {})

        if comment_id:
            recipient = {"comment_id": comment_id}
        else:
            recipient = {"id": recipient_id}

        request = {
            "recipient": recipient,
            "messaging_type": "RESPONSE"
        }

        if payload_type == "text":
            request["message"] = {
                "text": content.get("text", "")
            }
        elif payload_type in ("generic", "carousel"):
            # Build generic template payload
            elements = content.get("elements", [content])  # Single element if not carousel
            elements = self._sanitize_generic_elements(elements)

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

    @staticmethod
    def _sanitize_generic_elements(elements: Any) -> List[Dict[str, Any]]:
        """
        Normalize generic template elements/buttons to Graph-supported shape.

        Particularly important for postback buttons: Instagram rejects payloads when
        extra keys like `url` are included on a postback button.
        """
        output: List[Dict[str, Any]] = []
        for el in elements or []:
            if not isinstance(el, dict):
                continue

            sanitized: Dict[str, Any] = {}
            for key in ("title", "subtitle", "image_url"):
                value = el.get(key)
                if value is not None:
                    sanitized[key] = value

            raw_buttons = el.get("buttons") or []
            buttons: List[Dict[str, Any]] = []
            for btn in raw_buttons:
                if not isinstance(btn, dict):
                    continue
                btn_type = str(btn.get("type", "")).lower().strip()
                title = btn.get("title")
                if btn_type == "postback":
                    payload = btn.get("payload")
                    if title and payload:
                        buttons.append(
                            {"type": "postback", "title": title, "payload": payload}
                        )
                elif btn_type == "web_url":
                    url = btn.get("url")
                    if title and url:
                        buttons.append(
                            {"type": "web_url", "title": title, "url": url}
                        )

            if buttons:
                sanitized["buttons"] = buttons
            output.append(sanitized)

        return output

    @staticmethod
    def _sanitize_request_for_logging(request_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a log-safe copy of outbound payload.

        We intentionally mask recipient identifiers while preserving the exact
        message structure so template/debug issues are visible in logs.
        """
        safe = dict(request_body or {})
        recipient = dict(safe.get("recipient") or {})
        if "id" in recipient:
            recipient["id"] = "***"
        if "comment_id" in recipient:
            recipient["comment_id"] = "***"
        safe["recipient"] = recipient
        return safe

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
