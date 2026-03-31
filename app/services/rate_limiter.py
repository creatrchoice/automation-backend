"""Rate limiting service using Redis sliding window."""
import logging
import time
from typing import Dict
from datetime import datetime, timedelta
from app.db.redis import redis_client
from app.core.config import dm_settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter using Redis sorted sets for precise sliding window tracking.
    Tracks DM sends per account with a 1-hour sliding window.
    """

    def __init__(self, redis_conn=None):
        """Initialize with optional custom Redis connection."""
        self.redis = redis_conn or redis_client
        self.limit_per_hour = dm_settings.DM_RATE_LIMIT_PER_HOUR
        self.window_seconds = 3600  # 1 hour

    def _get_key(self, account_id: str) -> str:
        """Get Redis key for account rate limit tracking."""
        return f"dm:ratelimit:{account_id}:sends"

    def check_rate_limit(self, account_id: str) -> bool:
        """
        Check if account has exceeded rate limit in the current window.

        Args:
            account_id: Instagram account ID

        Returns:
            True if within limit, False if limit exceeded
        """
        try:
            key = self._get_key(account_id)
            now = time.time()
            window_start = now - self.window_seconds

            # Count sends in the sliding window
            count = self.redis.zcount(key, window_start, now)

            within_limit = count < self.limit_per_hour

            logger.debug(
                f"Rate limit check for {account_id}: "
                f"{count}/{self.limit_per_hour} sends in window, "
                f"within_limit={within_limit}"
            )

            return within_limit

        except Exception as e:
            logger.error(f"Error checking rate limit for {account_id}: {str(e)}")
            # Default to allow in case of Redis error
            return True

    def record_send(self, account_id: str) -> None:
        """
        Record a message send for the account.

        Adds timestamp to sorted set with automatic cleanup of old entries.

        Args:
            account_id: Instagram account ID
        """
        try:
            key = self._get_key(account_id)
            now = time.time()
            window_start = now - self.window_seconds

            # Add current timestamp to sorted set
            self.redis.zadd(key, {str(now): now})

            # Clean up entries older than window
            self.redis.zremrangebyscore(key, 0, window_start)

            # Set expiration on key (slightly larger than window for safety)
            self.redis.expire(key, self.window_seconds + 60)

            logger.debug(f"Recorded send for account {account_id} at {now}")

        except Exception as e:
            logger.error(f"Error recording send for {account_id}: {str(e)}")

    def get_rate_limit_status(self, account_id: str) -> Dict:
        """
        Get current rate limit status for an account.

        Args:
            account_id: Instagram account ID

        Returns:
            Dictionary with:
                - sent_this_hour: Number of DMs sent in current window
                - remaining: Remaining DMs available
                - resets_at: UTC datetime when oldest send expires from window
        """
        try:
            key = self._get_key(account_id)
            now = time.time()
            window_start = now - self.window_seconds

            # Get all timestamps in window
            entries = self.redis.zrange(key, 0, -1, withscores=True)

            # Count only entries in current window
            sent_count = sum(1 for _, score in entries if score >= window_start)
            remaining = max(0, self.limit_per_hour - sent_count)

            # Calculate reset time (when oldest entry expires)
            resets_at = None
            if entries:
                oldest_score = min(score for _, score in entries)
                resets_at = datetime.utcfromtimestamp(oldest_score + self.window_seconds)
            else:
                resets_at = datetime.utcnow()

            status = {
                "sent_this_hour": sent_count,
                "remaining": remaining,
                "resets_at": resets_at.isoformat(),
                "limit": self.limit_per_hour
            }

            logger.debug(f"Rate limit status for {account_id}: {status}")
            return status

        except Exception as e:
            logger.error(f"Error getting rate limit status for {account_id}: {str(e)}")
            return {
                "sent_this_hour": 0,
                "remaining": self.limit_per_hour,
                "resets_at": datetime.utcnow().isoformat(),
                "limit": self.limit_per_hour,
                "error": str(e)
            }

    def reset_account_limit(self, account_id: str) -> bool:
        """
        Reset (clear) rate limit for an account.

        Useful for testing or manual reset operations.

        Args:
            account_id: Instagram account ID

        Returns:
            True if successfully reset
        """
        try:
            key = self._get_key(account_id)
            self.redis.delete(key)
            logger.info(f"Reset rate limit for account {account_id}")
            return True
        except Exception as e:
            logger.error(f"Error resetting rate limit for {account_id}: {str(e)}")
            return False

    def get_account_limit_info(self, account_id: str) -> Dict:
        """
        Get comprehensive limit information for an account.

        Args:
            account_id: Instagram account ID

        Returns:
            Dictionary with limit configuration and current usage
        """
        return {
            "account_id": account_id,
            "limit_per_hour": self.limit_per_hour,
            "window_seconds": self.window_seconds,
            "status": self.get_rate_limit_status(account_id)
        }
