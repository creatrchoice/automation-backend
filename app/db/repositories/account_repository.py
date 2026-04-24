"""Data access helpers for Instagram account documents."""
from typing import Optional

from app.db.cosmos_db import cosmos_db
from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS


def resolve_account_id_by_ig_user_id(ig_user_id: str) -> Optional[str]:
    """Resolve internal account id using IG user id."""
    container = cosmos_db.get_container_client(CONTAINER_IG_ACCOUNTS)
    query = "SELECT TOP 1 c.id, c.account_id FROM c WHERE c.ig_user_id = @ig_user_id"
    rows = list(
        container.query_items(
            query=query,
            parameters=[{"name": "@ig_user_id", "value": ig_user_id}],
            enable_cross_partition_query=True,
        )
    )
    if not rows:
        return None
    row = rows[0]
    return row.get("account_id") or row.get("id")
