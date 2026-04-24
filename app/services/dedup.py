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

