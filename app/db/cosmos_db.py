"""Azure Cosmos DB client wrapper for DM Automation."""
import logging
from typing import Optional

from azure.cosmos import CosmosClient, exceptions
from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
from app.core.config import dm_settings

logger = logging.getLogger(__name__)


class CosmosDBClient:
    """Cosmos DB client with sync and async support."""

    def __init__(self):
        self.client: Optional[CosmosClient] = None
        self.async_client: Optional[AsyncCosmosClient] = None
        self._database_name = dm_settings.DM_DATABASE_NAME

    def connect(self) -> None:
        """Initialize synchronous Cosmos DB client."""
        if not dm_settings.AZURE_COSMOS_ENDPOINT or not dm_settings.AZURE_COSMOS_KEY:
            logger.warning("Cosmos DB credentials not configured")
            return

        try:
            self.client = CosmosClient(
                url=dm_settings.AZURE_COSMOS_ENDPOINT,
                credential=dm_settings.AZURE_COSMOS_KEY,
            )
            logger.info("Cosmos DB sync client connected")
        except Exception as e:
            logger.error(f"Failed to connect to Cosmos DB: {e}")
            raise

    async def connect_async(self) -> None:
        """Initialize asynchronous Cosmos DB client."""
        if not dm_settings.AZURE_COSMOS_ENDPOINT or not dm_settings.AZURE_COSMOS_KEY:
            logger.warning("Cosmos DB credentials not configured")
            return

        try:
            self.async_client = AsyncCosmosClient(
                url=dm_settings.AZURE_COSMOS_ENDPOINT,
                credential=dm_settings.AZURE_COSMOS_KEY,
            )
            logger.info("Cosmos DB async client connected")
        except Exception as e:
            logger.error(f"Failed to connect to Cosmos DB (async): {e}")
            raise

    def get_database_client(self):
        """Get sync database client."""
        if not self.client:
            self.connect()
        return self.client.get_database_client(self._database_name)

    def get_container_client(self, container_name: str):
        """Get sync container client."""
        db = self.get_database_client()
        return db.get_container_client(container_name)

    async def get_async_database_client(self):
        """Get async database client."""
        if not self.async_client:
            await self.connect_async()
        return self.async_client.get_database_client(self._database_name)

    async def get_async_container_client(self, container_name: str):
        """Get async container client."""
        db = await self.get_async_database_client()
        return db.get_container_client(container_name)

    async def close(self):
        """Close async client."""
        if self.async_client:
            await self.async_client.close()
            self.async_client = None


# Global instances
cosmos_db_client = CosmosDBClient()
cosmos_db = cosmos_db_client  # Alias for backward compatibility
