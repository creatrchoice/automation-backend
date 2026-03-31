"""Deduplication service using Redis with TTL."""
import logging
from typing import Optional
from app.db.redis import redis_client
from app.core.config import dm_settings

logger = logging.getLogger(__name__)


class DeduplicationService:
    """
    Deduplication service prevents duplicate message sends using Redis SET with TTL.

    A dedup key is created per (account_id, automation_id, ig_user_id) tuple.
    If the key exists, the message was already sent within the TTL window.
    """

    def __init__(self, redis_conn=None):
        """Initialize with optional custom Redis connection."""
        self.redis = redis_conn or redis_client
        self.default_ttl_hours = dm_settings.DEDUP_TTL_HOURS

    def _get_key(self, account_id: str, automation_id: str, ig_user_id: str) -> str:
        """Build Redis key for deduplication."""
        return f"dm:dedup:{account_id}:{automation_id}:{ig_user_id}"

    def check_and_set_dedup(
        self,
        account_id: str,
        automation_id: str,
        ig_user_id: str,
        ttl_hours: Optional[int] = None
    ) -> bool:
        """
        Check if message was already sent and set dedup key if new.

        Uses Redis SET with NX (only if not exists) and EX (expire) atomically.

        Args:
            account_id: Instagram account ID
            automation_id: Automation ID that triggered the send
            ig_user_id: Recipient IG user ID
            ttl_hours: TTL for dedup key in hours (defaults to DEDUP_TTL_HOURS)

        Returns:
            True if already sent (duplicate), False if new send (key was set)
        """
        try:
            key = self._get_key(account_id, automation_id, ig_user_id)
            ttl = ttl_hours or self.default_ttl_hours
            ttl_seconds = ttl * 3600

            # SET NX EX: set only if not exists, with expiration
            result = self.redis.set(
                key,
                "1",
                nx=True,  # Only set if not exists
                ex=ttl_seconds  # Expire after ttl_seconds
            )

            is_duplicate = result is None  # None means key already existed

            log_level = logging.DEBUG if is_duplicate else logging.DEBUG
            logger.log(
                log_level,
                f"Dedup check - account={account_id}, automation={automation_id}, "
                f"user={ig_user_id}: duplicate={is_duplicate}"
            )

            return is_duplicate

        except Exception as e:
            logger.error(
                f"Error in dedup check for {account_id}/{automation_id}/{ig_user_id}: {str(e)}"
            )
            # On error, allow send (fail open for dedup)
            return False

    def mark_sent(
        self,
        account_id: str,
        automation_id: str,
        ig_user_id: str,
        ttl_hours: Optional[int] = None
    ) -> bool:
        """
        Explicitly mark a message as sent (dedup key already set by check_and_set_dedup).

        This is a convenience method if you need to set dedup outside the check_and_set flow.

        Args:
            account_id: Instagram account ID
            automation_id: Automation ID
            ig_user_id: Recipient IG user ID
            ttl_hours: TTL for dedup key in hours

        Returns:
            True if successfully marked
        """
        try:
            key = self._get_key(account_id, automation_id, ig_user_id)
            ttl = ttl_hours or self.default_ttl_hours
            ttl_seconds = ttl * 3600

            self.redis.set(
                key,
                "1",
                ex=ttl_seconds
            )

            logger.debug(f"Marked as sent - key: {key}")
            return True

        except Exception as e:
            logger.error(f"Error marking sent for {key}: {str(e)}")
            return False

    def clear_dedup(
        self,
        account_id: str,
        automation_id: str,
        ig_user_id: str
    ) -> bool:
        """
        Clear (remove) a dedup key.

        Useful for testing or manual reset operations.

        Args:
            account_id: Instagram account ID
            automation_id: Automation ID
            ig_user_id: Recipient IG user ID

        Returns:
            True if successfully cleared
        """
        try:
            key = self._get_key(account_id, automation_id, ig_user_id)
            result = self.redis.delete(key)
            logger.debug(f"Cleared dedup - key: {key}, deleted={result > 0}")
            return result > 0

        except Exception as e:
            logger.error(f"Error clearing dedup for {key}: {str(e)}")
            return False

    def is_duplicate(
        self,
        account_id: str,
        automation_id: str,
        ig_user_id: str
    ) -> bool:
        """
        Check if message is a duplicate without setting the key.

        Use this if you want to check without marking as sent.

        Args:
            account_id: Instagram account ID
            automation_id: Automation ID
            ig_user_id: Recipient IG user ID

        Returns:
            True if key exists (duplicate), False if not exists
        """
        try:
            key = self._get_key(account_id, automation_id, ig_user_id)
            exists = self.redis.exists(key) > 0
            logger.debug(f"Is duplicate check - key: {key}, result={exists}")
            return exists

        except Exception as e:
            logger.error(f"Error checking duplicate for {key}: {str(e)}")
            return False

    def get_ttl(self, account_id: str, automation_id: str, ig_user_id: str) -> int:
        """
        Get remaining TTL (in seconds) for a dedup key.

        Args:
            account_id: Instagram account ID
            automation_id: Automation ID
            ig_user_id: Recipient IG user ID

        Returns:
            TTL in seconds, or -1 if key doesn't exist, -2 if no expiration set
        """
        try:
            key = self._get_key(account_id, automation_id, ig_user_id)
            ttl = self.redis.ttl(key)
            logger.debug(f"TTL for key {key}: {ttl}")
            return ttl

        except Exception as e:
            logger.error(f"Error getting TTL for {key}: {str(e)}")
            return -1
