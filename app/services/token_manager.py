"""Token management service: encryption, decryption, and refresh."""
import logging
from typing import Any, Dict, Optional
from app.core.security import TokenEncryption
from app.core.config import dm_settings
from app.db.cosmos_db import CosmosDBClient
from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS
import httpx

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages token encryption, decryption, and refresh operations."""

    def __init__(self, cosmos_client: Optional[CosmosDBClient] = None):
        """Initialize token manager with optional Cosmos DB client."""
        self.cosmos_client = cosmos_client or CosmosDBClient()
        self.encryption = TokenEncryption()

    def encrypt_token(self, plaintext_token: str) -> str:
        """
        Encrypt a plaintext token for secure storage.

        Args:
            plaintext_token: Raw access token from Instagram

        Returns:
            Encrypted token string (base64-encoded)

        Raises:
            SecurityError: If encryption fails
        """
        try:
            logger.debug("Encrypting token")
            encrypted = TokenEncryption.encrypt_token(plaintext_token)
            logger.debug("Token encrypted successfully")
            return encrypted
        except SecurityError as e:
            logger.error(f"Token encryption failed: {str(e)}")
            raise

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypt an encrypted token for API use.

        Args:
            encrypted_token: Base64-encoded encrypted token

        Returns:
            Decrypted plaintext token

        Raises:
            SecurityError: If decryption fails
        """
        try:
            logger.debug("Decrypting token")
            plaintext = TokenEncryption.decrypt_token(encrypted_token)
            logger.debug("Token decrypted successfully")
            return plaintext
        except SecurityError as e:
            logger.error(f"Token decryption failed: {str(e)}")
            raise

    def get_account_document(self, account_id: str) -> Dict[str, Any]:
        """
        Load full account document from Cosmos (by c.id).

        Args:
            account_id: Internal account id (e.g. instagram_{ig_user_id})

        Returns:
            Account document dict

        Raises:
            ValueError: If account not found
        """
        logger.debug(f"Loading account {account_id} from Cosmos DB")
        container = self.cosmos_client.get_container_client(
            CONTAINER_IG_ACCOUNTS
        )
        query = "SELECT * FROM c WHERE c.id = @account_id"
        items = list(
            container.query_items(
                query=query,
                parameters=[{"name": "@account_id", "value": account_id}],
                enable_cross_partition_query=True,
            )
        )
        if not items:
            logger.error(f"Account {account_id} not found in Cosmos DB")
            raise ValueError(f"Account {account_id} not found")
        return items[0]

    @staticmethod
    def graph_user_id_from_document(account: Dict[str, Any], account_id: str) -> str:
        """Resolve IG user id for Graph URL paths from a loaded account document."""
        ig = account.get("ig_user_id")
        if ig is not None and str(ig).strip() != "":
            return str(ig)
        if account_id.startswith("instagram_"):
            return account_id[len("instagram_") :]
        return account_id

    def get_graph_api_user_id(self, account_id: str) -> str:
        """
        Instagram Graph paths use the numeric IG user id (e.g. /{ig-user-id}/messages),
        not the internal document id prefix.

        Args:
            account_id: Internal id (instagram_...) or raw ig_user_id

        Returns:
            String IG user id for URL path segments
        """
        account = self.get_account_document(account_id)
        return self.graph_user_id_from_document(account, account_id)

    def get_decrypted_account_token(self, account_id: str) -> str:
        """
        Load account from Cosmos DB and decrypt its access token.

        Args:
            account_id: Instagram account ID

        Returns:
            Decrypted access token

        Raises:
            ValueError: If account not found
            SecurityError: If decryption fails
        """
        try:
            account = self.get_account_document(account_id)
            encrypted_token = account.get("access_token")

            if not encrypted_token:
                logger.error(f"No access token found for account {account_id}")
                raise ValueError(f"No access token for account {account_id}")

            return self.decrypt_token(encrypted_token)

        except Exception as e:
            logger.error(f"Error getting decrypted token for account {account_id}: {str(e)}")
            raise

    async def refresh_long_lived_token(self, account_id: str) -> bool:
        """
        Refresh Instagram long-lived access token.

        Uses the refresh endpoint: GET graph.instagram.com/refresh_access_token
        Only works for long-lived tokens (user-level or page-level).

        Args:
            account_id: Account ID to refresh token for

        Returns:
            True if refresh successful, False otherwise
        """
        try:
            logger.info(f"Refreshing access token for account {account_id}")

            try:
                account = self.get_account_document(account_id)
            except ValueError:
                logger.error(f"Account {account_id} not found")
                return False

            container = self.cosmos_client.get_container_client(
                CONTAINER_IG_ACCOUNTS
            )
            current_token = self.decrypt_token(account["access_token"])

            # Call Instagram refresh endpoint
            async with httpx.AsyncClient() as client:
                url = f"{dm_settings.INSTAGRAM_API_BASE_URL}/{dm_settings.INSTAGRAM_API_VERSION}/refresh_access_token"
                params = {
                    "grant_type": "ig_refresh_token",
                    "access_token": current_token
                }

                logger.debug(f"Calling refresh endpoint for account {account_id}")
                response = await client.get(url, params=params)

                if response.status_code != 200:
                    logger.error(
                        f"Token refresh failed for {account_id}: "
                        f"status={response.status_code}, response={response.text}"
                    )
                    return False

                response_data = response.json()
                new_token = response_data.get("access_token")
                expires_in = response_data.get("expires_in")

                if not new_token:
                    logger.error(f"No token in refresh response for {account_id}")
                    return False

                # Encrypt new token
                encrypted_new_token = self.encrypt_token(new_token)

                # Update in Cosmos DB
                updated_account = account.copy()
                updated_account["access_token"] = encrypted_new_token

                if expires_in:
                    from datetime import datetime, timedelta
                    updated_account["access_token_expires_at"] = (
                        datetime.utcnow() + timedelta(seconds=expires_in)
                    ).isoformat()

                updated_account["updated_at"] = datetime.utcnow().isoformat()

                logger.debug(f"Updating account {account_id} with new token")
                container.replace_item(
                    item=account_id,
                    body=updated_account,
                    partition_key=updated_account.get("user_id"),
                )

                logger.info(f"Token refreshed successfully for account {account_id}")
                return True

        except Exception as e:
            logger.error(f"Error refreshing token for {account_id}: {str(e)}")
            return False


# Global singleton instance
token_manager = TokenManager()
