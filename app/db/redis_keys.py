"""Redis key pattern helpers for rate limits, dedup, automation cache, account map."""
from typing import Optional
from datetime import timedelta


class RedisKeyPatterns:
    """Redis key naming patterns for DM automation."""

    # Key prefixes
    PREFIX_RATE_LIMIT = "dm:rate_limit"
    PREFIX_DEDUP = "dm:dedup"
    PREFIX_CACHE = "dm:cache"
    PREFIX_ACCOUNT_MAP = "dm:account_map"
    PREFIX_WEBHOOK = "dm:webhook"
    PREFIX_SESSION = "dm:session"
    PREFIX_TEMP = "dm:temp"

    # Rate limiting keys
    @staticmethod
    def dm_per_hour_key(account_id: str) -> str:
        """
        Key for DM rate limit (per hour).

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_RATE_LIMIT}:dm_per_hour:{account_id}"

    @staticmethod
    def contact_query_per_hour_key(account_id: str) -> str:
        """
        Key for contact query rate limit (per hour).

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_RATE_LIMIT}:contact_query:{account_id}"

    @staticmethod
    def webhook_per_second_key(account_id: str) -> str:
        """
        Key for webhook event rate limit (per second).

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_RATE_LIMIT}:webhook:{account_id}"

    @staticmethod
    def api_calls_today_key(account_id: str) -> str:
        """
        Key for tracking API calls per day.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_RATE_LIMIT}:api_calls:{account_id}"

    # Deduplication keys
    @staticmethod
    def message_dedup_key(instagram_message_id: str) -> str:
        """
        Key for message deduplication.

        Prevents processing same webhook event twice.

        Args:
            instagram_message_id: Message ID from Instagram

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_DEDUP}:msg:{instagram_message_id}"

    @staticmethod
    def webhook_event_dedup_key(webhook_event_id: str) -> str:
        """
        Key for webhook event deduplication.

        Args:
            webhook_event_id: Event ID from Instagram webhook

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_DEDUP}:event:{webhook_event_id}"

    @staticmethod
    def contact_dedup_key(account_id: str, ig_id: str) -> str:
        """
        Key for contact deduplication during import.

        Args:
            account_id: Instagram account ID
            ig_id: Instagram user ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_DEDUP}:contact:{account_id}:{ig_id}"

    # Automation cache keys
    @staticmethod
    def automation_cache_key(automation_id: str) -> str:
        """
        Key for caching automation configuration.

        Args:
            automation_id: Automation ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_CACHE}:automation:{automation_id}"

    @staticmethod
    def automation_list_cache_key(user_id: str) -> str:
        """
        Key for caching user's automation list.

        Args:
            user_id: User ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_CACHE}:automations:{user_id}"

    @staticmethod
    def message_template_cache_key(template_id: str) -> str:
        """
        Key for caching message template.

        Args:
            template_id: Template ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_CACHE}:template:{template_id}"

    @staticmethod
    def automation_trigger_cache_key(account_id: str) -> str:
        """
        Key for caching triggers for an account.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_CACHE}:triggers:{account_id}"

    # Account mapping keys
    @staticmethod
    def user_to_accounts_key(user_id: str) -> str:
        """
        Key for mapping user to their Instagram accounts.

        Args:
            user_id: User ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_ACCOUNT_MAP}:user_accounts:{user_id}"

    @staticmethod
    def account_to_user_key(account_id: str) -> str:
        """
        Key for reverse mapping: account to user.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_ACCOUNT_MAP}:account_user:{account_id}"

    @staticmethod
    def account_details_cache_key(account_id: str) -> str:
        """
        Key for caching account details.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_ACCOUNT_MAP}:details:{account_id}"

    # Webhook processing keys
    @staticmethod
    def webhook_processing_key(account_id: str) -> str:
        """
        Key for tracking in-progress webhook processing.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_WEBHOOK}:processing:{account_id}"

    @staticmethod
    def webhook_retry_key(webhook_event_id: str) -> str:
        """
        Key for webhook retry queue.

        Args:
            webhook_event_id: Event ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_WEBHOOK}:retry:{webhook_event_id}"

    @staticmethod
    def webhook_failed_key(account_id: str) -> str:
        """
        Key for tracking failed webhook events.

        Args:
            account_id: Instagram account ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_WEBHOOK}:failed:{account_id}"

    # Session keys
    @staticmethod
    def user_session_key(user_id: str, session_id: str) -> str:
        """
        Key for user session tracking.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_SESSION}:{user_id}:{session_id}"

    @staticmethod
    def oauth_state_key(state: str) -> str:
        """
        Key for OAuth flow state validation.

        Args:
            state: State value

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_SESSION}:oauth_state:{state}"

    # Temporary data keys
    @staticmethod
    def contact_import_progress_key(import_id: str) -> str:
        """
        Key for tracking contact import progress.

        Args:
            import_id: Import job ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_TEMP}:import:{import_id}"

    @staticmethod
    def automation_test_key(user_id: str, test_id: str) -> str:
        """
        Key for temporary automation test data.

        Args:
            user_id: User ID
            test_id: Test ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_TEMP}:test:{user_id}:{test_id}"

    @staticmethod
    def bulk_operation_key(operation_id: str) -> str:
        """
        Key for bulk operation progress.

        Args:
            operation_id: Operation ID

        Returns:
            Redis key
        """
        return f"{RedisKeyPatterns.PREFIX_TEMP}:bulk_op:{operation_id}"


class RedisExpiration:
    """Standard expiration times for Redis keys."""

    # Rate limiting (typically 1 hour)
    RATE_LIMIT_PER_HOUR = 3600  # seconds
    RATE_LIMIT_PER_SECOND = 60  # seconds (window)

    # Deduplication (24 hours by default, configurable)
    MESSAGE_DEDUP_TTL = 24 * 3600  # seconds
    WEBHOOK_DEDUP_TTL = 24 * 3600  # seconds
    CONTACT_DEDUP_TTL = 1 * 3600  # 1 hour

    # Caching
    AUTOMATION_CACHE_TTL = 2 * 3600  # 2 hours
    TEMPLATE_CACHE_TTL = 2 * 3600  # 2 hours
    ACCOUNT_DETAILS_CACHE_TTL = 6 * 3600  # 6 hours
    TRIGGER_CACHE_TTL = 2 * 3600  # 2 hours

    # Account mapping (longer lived)
    ACCOUNT_MAP_TTL = 6 * 3600  # 6 hours

    # Webhook/session
    WEBHOOK_PROCESSING_TTL = 300  # 5 minutes
    WEBHOOK_RETRY_TTL = 86400  # 24 hours
    SESSION_TTL = 30 * 24 * 3600  # 30 days
    OAUTH_STATE_TTL = 600  # 10 minutes

    # Temporary data
    IMPORT_PROGRESS_TTL = 7 * 24 * 3600  # 7 days
    TEST_DATA_TTL = 3600  # 1 hour
    BULK_OPERATION_TTL = 24 * 3600  # 24 hours

    @staticmethod
    def get_expiration_timedelta(ttl_seconds: int) -> timedelta:
        """Convert seconds to timedelta."""
        return timedelta(seconds=ttl_seconds)
