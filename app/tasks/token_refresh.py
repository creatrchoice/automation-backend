"""Celery task for refreshing expired Instagram API tokens."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.core.config import dm_settings
from app.db.cosmos_db import cosmos_db

logger = logging.getLogger(__name__)


class TokenRefreshTask:
    """Handle token refresh for Instagram accounts."""

    def __init__(self):
        """Initialize token refresh task."""
        self.accounts_container = dm_settings.DM_IG_ACCOUNTS_CONTAINER
        self.token_expiry_buffer_days = 10  # Refresh tokens expiring in 10 days

    def refresh_expired_tokens(self) -> Dict[str, Any]:
        """
        Query accounts with tokens expiring in 10 days and refresh them.

        This task runs daily at 3 AM.

        Returns:
            Task result with counts
        """
        try:
            logger.info("Starting token refresh task")

            # Find accounts with tokens expiring soon
            expiring_accounts = self._find_expiring_tokens()

            if not expiring_accounts:
                logger.info("No accounts with expiring tokens found")
                return {"status": "success", "refreshed_count": 0, "failed_count": 0}

            logger.info(f"Found {len(expiring_accounts)} accounts with expiring tokens")

            refreshed_count = 0
            failed_count = 0

            # Refresh each token
            for account in expiring_accounts:
                try:
                    success = self._refresh_account_token(account)
                    if success:
                        refreshed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing token for account {account.get('id')}: {str(e)}")
                    failed_count += 1

            logger.info(
                f"Token refresh completed: {refreshed_count} succeeded, {failed_count} failed"
            )

            return {
                "status": "success",
                "refreshed_count": refreshed_count,
                "failed_count": failed_count,
            }

        except Exception as e:
            logger.exception(f"Error in token refresh task: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _find_expiring_tokens(self) -> List[Dict[str, Any]]:
        """
        Find accounts with tokens expiring within the buffer period.

        Returns:
            List of accounts with expiring tokens
        """
        try:
            container = cosmos_db.get_container_client(self.accounts_container)

            # Calculate expiry threshold
            now = datetime.utcnow()
            expiry_threshold = (now + timedelta(days=self.token_expiry_buffer_days)).isoformat()

            # Query for accounts with token_expires before threshold
            query = (
                "SELECT c.* FROM c "
                "WHERE c.token_expires < @expiry_threshold "
                "AND c.status = 'active' "
                "ORDER BY c.token_expires ASC"
            )

            results = list(
                container.query_items(
                    query=query,
                    parameters=[{"name": "@expiry_threshold", "value": expiry_threshold}],
                )
            )

            logger.debug(f"Found {len(results)} accounts with expiring tokens")
            return results

        except Exception as e:
            logger.error(f"Error finding expiring tokens: {str(e)}")
            return []

    def _refresh_account_token(self, account: Dict[str, Any]) -> bool:
        """
        Refresh token for a single account via Instagram API.

        Args:
            account: Account data from Cosmos DB

        Returns:
            True if successful, False otherwise
        """
        try:
            account_id = account.get("id")
            logger.info(f"Refreshing token for account {account_id}")

            from app.services.instagram_api import instagram_api
            from app.services.token_manager import token_manager

            # Refresh token via Instagram API
            new_token_data = instagram_api.refresh_long_lived_token(
                account.get("access_token")
            )

            if not new_token_data:
                logger.error(f"Failed to refresh token via Instagram API for account {account_id}")
                return False

            # Encrypt and store new token
            encrypted_token = token_manager.encrypt_token(new_token_data["access_token"])

            # Update account in Cosmos DB
            account["access_token"] = encrypted_token
            account["token_expires"] = new_token_data.get(
                "expires_in", 5184000  # 60 days default
            )
            account["token_refreshed_at"] = datetime.utcnow().isoformat()

            # Calculate new expiry date
            token_expiry_date = datetime.utcnow() + timedelta(
                seconds=new_token_data.get("expires_in", 5184000)
            )
            account["token_expires_at"] = token_expiry_date.isoformat()

            container = cosmos_db.get_container_client(self.accounts_container)
            container.replace_item(account["id"], account)

            logger.info(f"Successfully refreshed token for account {account_id}")
            return True

        except Exception as e:
            logger.error(f"Error refreshing account token: {str(e)}")
            return False


# Global task instance
token_refresh_task = TokenRefreshTask()


# Celery task
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def refresh_expired_tokens(self):
    """
    Celery task to refresh expired Instagram tokens.

    This is scheduled to run daily at 3 AM.
    """
    try:
        result = token_refresh_task.refresh_expired_tokens()
        logger.info(f"Token refresh task result: {result}")
        return result

    except Exception as e:
        logger.error(f"Token refresh task failed: {str(e)}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
