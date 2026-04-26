"""Data access helpers for automation documents."""
from typing import Any, Dict, List

from app.db.cosmos_db import cosmos_db
from app.db.cosmos_containers import CONTAINER_AUTOMATIONS


def list_enabled_automations_for_account(account_id: str) -> List[Dict[str, Any]]:
    """
    Load enabled automations for an account from Cosmos DB.

    Uses a targeted query against account_id and enabled flag.
    """
    container = cosmos_db.get_container_client(CONTAINER_AUTOMATIONS)
    # Cosmos in this setup rejects `SELECT c.*` with BadRequest for this container.
    # `SELECT *` with the same predicates works reliably.
    query = "SELECT * FROM c WHERE c.account_id = @account_id AND c.enabled = true"
    return list(
        container.query_items(
            query=query,
            parameters=[{"name": "@account_id", "value": account_id}],
            enable_cross_partition_query=True,
        )
    )


def list_all_enabled_automations() -> List[Dict[str, Any]]:
    """Fallback fetch for enabled automations across accounts."""
    container = cosmos_db.get_container_client(CONTAINER_AUTOMATIONS)
    return list(
        container.query_items(
            query="SELECT * FROM c WHERE c.enabled = true",
            enable_cross_partition_query=True,
        )
    )
