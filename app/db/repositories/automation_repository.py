"""Data access helpers for automation documents."""
import logging
from typing import Any, Dict, List

from azure.cosmos import exceptions

from app.db.cosmos_db import cosmos_db
from app.db.cosmos_containers import CONTAINER_AUTOMATIONS

logger = logging.getLogger(__name__)


def list_enabled_automations_for_account(account_id: str) -> List[Dict[str, Any]]:
    """
    Load enabled automations for an account from Cosmos DB.

    Uses a targeted query when possible; on BadRequest (known SDK / partition
    quirks with cross-partition + parameters), falls back to scanning enabled
    automations and filtering by account_id in process.
    """
    container = cosmos_db.get_container_client(CONTAINER_AUTOMATIONS)
    query = "SELECT c.* FROM c WHERE c.account_id = @account_id AND c.enabled = true"
    try:
        return list(
            container.query_items(
                query=query,
                parameters=[{"name": "@account_id", "value": account_id}],
                enable_cross_partition_query=True,
            )
        )
    except exceptions.CosmosHttpResponseError as e:
        if e.status_code != 400:
            raise
        logger.warning(
            "list_enabled_automations_for_account query failed for %s, using fallback: %s",
            account_id,
            e,
        )
        return [
            a
            for a in list_all_enabled_automations()
            if str(a.get("account_id")) == str(account_id) and a.get("enabled") is True
        ]


def list_all_enabled_automations() -> List[Dict[str, Any]]:
    """Fallback fetch for enabled automations across accounts."""
    container = cosmos_db.get_container_client(CONTAINER_AUTOMATIONS)
    return list(
        container.query_items(
            query="SELECT * FROM c WHERE c.enabled = true",
            enable_cross_partition_query=True,
        )
    )
