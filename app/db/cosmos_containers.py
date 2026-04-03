"""Cosmos DB container initialization with partition keys for DM automation."""
from typing import Dict, Any
from azure.cosmos import PartitionKey, exceptions
from app.db.cosmos_db import cosmos_db_client
from app.core.config import dm_settings
import logging

logger = logging.getLogger(__name__)


class DMContainers:
    """DM Automation Cosmos DB containers configuration."""

    # Container definitions with partition keys
    CONTAINERS_CONFIG: Dict[str, Dict[str, Any]] = {
        "dm_users": {
            "partition_key": PartitionKey(path="/partition_key"),
            "description": "User accounts with subscription info",
            "throughput": 400
        },
        "dm_ig_accounts": {
            "partition_key": PartitionKey(path="/user_id"),
            "description": "Connected Instagram accounts",
            "throughput": 400
        },
        "dm_automations": {
            "partition_key": PartitionKey(path="/user_id"),
            "description": "Automations with steps and templates",
            "throughput": 400
        },
        "dm_contacts": {
            "partition_key": PartitionKey(path="/account_id"),
            "description": "Contacts for messaging",
            "throughput": 400
        },
        "dm_message_logs": {
            "partition_key": PartitionKey(path="/account_id"),
            "description": "Message delivery logs with latency tracking",
            "throughput": 400
        },
        "dm_webhook_events": {
            "partition_key": PartitionKey(path="/account_id"),
            "description": "Raw webhook events from Instagram",
            "throughput": 400
        },
        "dm_scheduled_tasks": {
            "partition_key": PartitionKey(path="/account_id"),
            "description": "Scheduled follow-ups and tasks",
            "throughput": 400
        },
        "dm_analytics": {
            "partition_key": PartitionKey(path="/account_id"),
            "description": "Daily analytics aggregates",
            "throughput": 400
        },
        "dm_organizations": {
            "partition_key": PartitionKey(path="/id"),
            "description": "Organizations / workspaces with members and roles",
            "throughput": 400
        },
        "dm_invitations": {
            "partition_key": PartitionKey(path="/org_id"),
            "description": "Pending team invitation tokens",
            "throughput": 400
        }
    }

    @staticmethod
    def create_all_containers_if_not_exists() -> None:
        """
        Create all DM automation containers if they don't exist.

        Each container is configured with an appropriate partition key:
        - dm_users: /partition_key (static "user" for user account lookups)
        - dm_ig_accounts: /user_id (query all accounts for a user)
        - dm_automations: /user_id (query all automations for a user)
        - dm_contacts: /account_id (query all contacts for an account)
        - dm_message_logs: /account_id (query messages for an account)
        - dm_webhook_events: /account_id (query webhook events for an account)
        - dm_scheduled_tasks: /account_id (query tasks for an account)
        - dm_analytics: /account_id (query analytics for an account)
        """
        if not cosmos_db_client.client:
            cosmos_db_client.connect()

        # Create database if it doesn't exist
        try:
            cosmos_db_client.client.create_database_if_not_exists(
                id=dm_settings.DM_DATABASE_NAME
            )
            logger.info(f"Database '{dm_settings.DM_DATABASE_NAME}' ready")
        except exceptions.CosmosHttpResponseError as e:
            if e.status_code != 409:  # 409 = already exists
                raise

        db_client = cosmos_db_client.client.get_database_client(dm_settings.DM_DATABASE_NAME)

        # Create each container
        for container_id, config in DMContainers.CONTAINERS_CONFIG.items():
            try:
                logger.info(f"Creating container '{container_id}'...")
                try:
                    # Try with throughput first (provisioned accounts)
                    db_client.create_container_if_not_exists(
                        id=container_id,
                        partition_key=config["partition_key"],
                        offer_throughput=config.get("throughput", 400)
                    )
                except exceptions.CosmosHttpResponseError as e:
                    if "serverless" in str(e).lower() or e.status_code == 400:
                        # Serverless account - create without throughput
                        logger.info(f"Creating serverless container '{container_id}'...")
                        db_client.create_container_if_not_exists(
                            id=container_id,
                            partition_key=config["partition_key"]
                        )
                    elif e.status_code != 409:  # 409 = already exists
                        raise

                logger.info(f"Container '{container_id}' ready")

            except Exception as e:
                logger.error(f"Error creating container '{container_id}': {str(e)}")
                raise

    @staticmethod
    def get_container(container_name: str):
        """
        Get a container client by name.

        Args:
            container_name: Name of the container (e.g., 'dm_users')

        Returns:
            Container client

        Raises:
            ValueError: If container name is invalid
        """
        if container_name not in DMContainers.CONTAINERS_CONFIG:
            raise ValueError(
                f"Unknown container: {container_name}. "
                f"Valid containers: {list(DMContainers.CONTAINERS_CONFIG.keys())}"
            )

        return cosmos_db_client.get_container_client(container_name)

    @staticmethod
    async def get_async_container(container_name: str):
        """
        Get an async container client by name.

        Args:
            container_name: Name of the container

        Returns:
            Async container client
        """
        if container_name not in DMContainers.CONTAINERS_CONFIG:
            raise ValueError(
                f"Unknown container: {container_name}. "
                f"Valid containers: {list(DMContainers.CONTAINERS_CONFIG.keys())}"
            )

        return await cosmos_db_client.get_async_container_client(container_name)

    @staticmethod
    def get_partition_key(container_name: str) -> str:
        """
        Get the partition key path for a container.

        Args:
            container_name: Container name

        Returns:
            Partition key path (e.g., '/user_id')
        """
        if container_name not in DMContainers.CONTAINERS_CONFIG:
            raise ValueError(f"Unknown container: {container_name}")

        return DMContainers.CONTAINERS_CONFIG[container_name]["partition_key"].path


# Container name constants for easy reference
CONTAINER_USERS = "dm_users"
CONTAINER_IG_ACCOUNTS = "dm_ig_accounts"
CONTAINER_AUTOMATIONS = "dm_automations"
CONTAINER_CONTACTS = "dm_contacts"
CONTAINER_MESSAGE_LOGS = "dm_message_logs"
CONTAINER_WEBHOOK_EVENTS = "dm_webhook_events"
CONTAINER_SCHEDULED_TASKS = "dm_scheduled_tasks"
CONTAINER_ANALYTICS = "dm_analytics"
CONTAINER_ORGANIZATIONS = "dm_organizations"
CONTAINER_INVITATIONS = "dm_invitations"

ALL_CONTAINERS = [
    CONTAINER_USERS,
    CONTAINER_IG_ACCOUNTS,
    CONTAINER_AUTOMATIONS,
    CONTAINER_CONTACTS,
    CONTAINER_MESSAGE_LOGS,
    CONTAINER_WEBHOOK_EVENTS,
    CONTAINER_SCHEDULED_TASKS,
    CONTAINER_ANALYTICS,
    CONTAINER_ORGANIZATIONS,
    CONTAINER_INVITATIONS,
]


async def initialize_containers():
    """
    Initialize all Cosmos DB containers on application startup.
    Called from main.py lifespan.
    """
    try:
        DMContainers.create_all_containers_if_not_exists()
        logger.info("All DM automation containers initialized")
    except Exception as e:
        logger.error(f"Container initialization failed: {e}")
        raise
