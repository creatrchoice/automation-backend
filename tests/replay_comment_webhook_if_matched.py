#!/usr/bin/env python3
"""
Load the newest dm_webhook_events row that contains an Instagram *comment* change
and, when an automation would match, POST the saved raw body to the webhook
(X-Hub-Signature-256) so the app processes it. Does not run separate DB/validation
checks beyond the same ``CommentProcessor`` matching used in production.

Manual script (not run in CI). From repo root:

  PYTHONPATH=. python tests/replay_comment_webhook_if_matched.py

Env:
  AZURE_COSMOS_ENDPOINT, AZURE_COSMOS_KEY, DM_DATABASE_NAME
  INSTAGRAM_APP_SECRET
  WEBHOOK_REPLAY_URL — default http://127.0.0.1:8000/api/v1/webhooks/instagram
  WEBHOOK_EVENT_SCAN_LIMIT — max recent rows to scan (default 50)

DB match only (Cosmos → same ``CommentProcessor`` rules as production; no HTTP):

  PYTHONPATH=. python tests/check_db_webhook_automation_match.py
  # or: CHECK_DB_MATCH=1 PYTHONPATH=. python tests/replay_comment_webhook_if_matched.py
"""
import hashlib
import hmac
import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    import pytest

    pytestmark = pytest.mark.skip(
        reason="Manual Cosmos+webhook script; excluded from CI."
    )
except ImportError:
    pass

try:
    import httpx
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

try:
    from azure.cosmos import CosmosClient
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "azure-cosmos", "-q"])
    from azure.cosmos import CosmosClient

from dotenv import load_dotenv

load_dotenv()

from app.core.config import dm_settings
from app.workers.comment_processor import CommentProcessor

WEBHOOK_CONTAINER = "dm_webhook_events"

try:
    _limit = max(1, int(os.getenv("WEBHOOK_EVENT_SCAN_LIMIT", "50")))
except ValueError:
    _limit = 50
WEBHOOK_EVENT_SCAN_LIMIT = _limit

DEFAULT_REPLAY = "http://127.0.0.1:8000/api/v1/webhooks/instagram"
WEBHOOK_REPLAY_URL = os.getenv("WEBHOOK_REPLAY_URL", DEFAULT_REPLAY).rstrip("/")


def _payload_from_doc(doc: dict) -> Optional[dict]:
    raw = doc.get("raw_payload")
    if raw is not None and isinstance(raw, dict):
        return raw
    body = doc.get("raw_body")
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _first_scanned_row_with_comment(rows: list) -> Optional[dict]:
    """Newest-first rows: return first document whose payload has a comment change."""
    for doc in rows:
        payload = _payload_from_doc(doc)
        if not payload or str(payload.get("object", "")).lower() != "instagram":
            continue
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    return doc
    return None


def _comment_envelopes_from_payload(payload: dict) -> List[dict]:
    out: List[dict] = []
    for entry in payload.get("entry", []):
        ig_account_id = entry.get("id")
        ts = entry.get("time")
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            out.append(
                {
                    "ig_account_id": ig_account_id,
                    "webhook_timestamp": ts,
                    "event": change,
                    "event_source": "changes",
                    "field": change.get("field"),
                }
            )
    return out


def any_comment_envelope_matches(processor: CommentProcessor, payload: dict) -> bool:
    """True if at least one comment envelope matches an enabled automation (same as live path)."""
    return bool(matching_automation_ids_for_payload(processor, payload))


def _payload_has_instagram_comment(payload: dict) -> bool:
    if str(payload.get("object", "")).lower() != "instagram":
        return False
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                return True
    return False


def matching_automation_ids_for_payload(
    processor: CommentProcessor, payload: dict
) -> List[str]:
    """
    Ids of enabled automations in ``dm_automations`` that would run for this payload
    (order preserved, deduped).
    """
    seen = set()
    out: List[str] = []
    for env in _comment_envelopes_from_payload(payload):
        comment_data = processor._extract_comment_data(env)
        if not comment_data:
            continue
        account_id = processor._resolve_account_id(comment_data["ig_user_id"])
        if not account_id:
            continue
        for auto in processor._match_automations(account_id, "comment", comment_data):
            aid = str(auto.get("id", "") or "")
            if aid and aid not in seen:
                seen.add(aid)
                out.append(aid)
    return out


def main_check_db() -> int:
    """
    Query ``dm_webhook_events`` (newest first, limit N). For each row with an Instagram
    *comment* change, evaluate automation match against ``dm_automations`` the same
    way as the live worker. Print the first (newest) row that has a match, or a
    no-match summary. No HTTP, no app secret.
    """
    try:
        rows = fetch_recent_webhook_rows(WEBHOOK_EVENT_SCAN_LIMIT)
    except Exception as e:
        print(f"Cosmos query failed: {e}", file=sys.stderr)
        return 2

    processor = CommentProcessor()
    first_comment: Optional[dict] = None
    for doc in rows:
        payload = _payload_from_doc(doc)
        if not payload or not _payload_has_instagram_comment(payload):
            continue
        if first_comment is None:
            first_comment = doc
        auto_ids = matching_automation_ids_for_payload(processor, payload)
        if auto_ids:
            print("MATCH: stored webhook row matches enabled automation(s) in dm_automations.")
            print(
                f"  container: {WEBHOOK_CONTAINER}\n"
                f"  id: {doc.get('id')}\n"
                f"  received_at: {doc.get('received_at')}\n"
                f"  account_id (doc): {doc.get('account_id')}\n"
                f"  matched_automation_id(s): {', '.join(auto_ids)}"
            )
            return 0

    if first_comment is None:
        print(
            f"NO COMMENT WEBHOOKS: none of the {WEBHOOK_EVENT_SCAN_LIMIT} newest rows "
            f"in {WEBHOOK_CONTAINER} contain an Instagram *comments* change."
        )
        return 0

    print(
        "NO MATCH: at least one comment webhook exists in the batch, but none of them "
        "match any enabled automation (trigger, post, keywords, account resolution)."
    )
    print(
        f"  (newest comment row) id: {first_comment.get('id')}  "
        f"received_at: {first_comment.get('received_at')}"
    )
    return 1


def _body_bytes_for_replay(doc: dict, payload: Dict[str, Any]) -> bytes:
    raw_body = doc.get("raw_body")
    if raw_body and isinstance(raw_body, str):
        return raw_body.encode("utf-8")
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign_body(body: bytes) -> str:
    secret = (dm_settings.INSTAGRAM_APP_SECRET or "").encode("utf-8")
    if not secret or secret == b"":
        raise SystemExit("INSTAGRAM_APP_SECRET is not set; cannot sign the webhook request")
    dig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"sha256={dig}"


def fetch_recent_webhook_rows(limit: int) -> list:
    endpoint = os.getenv("AZURE_COSMOS_ENDPOINT")
    key = os.getenv("AZURE_COSMOS_KEY")
    if not endpoint or not key:
        raise SystemExit("AZURE_COSMOS_ENDPOINT and AZURE_COSMOS_KEY must be set")
    db_name = os.getenv("DM_DATABASE_NAME", "dm_automation_db")
    client = CosmosClient(endpoint, credential=key)
    db = client.get_database_client(db_name)
    container = db.get_container_client(WEBHOOK_CONTAINER)
    results = list(
        container.query_items(
            query="SELECT * FROM c ORDER BY c.received_at DESC OFFSET 0 LIMIT @limit",
            parameters=[{"name": "@limit", "value": limit}],
            enable_cross_partition_query=True,
        )
    )
    return results


def main() -> int:
    try:
        rows = fetch_recent_webhook_rows(WEBHOOK_EVENT_SCAN_LIMIT)
    except Exception as e:
        print(f"Cosmos query failed: {e}", file=sys.stderr)
        return 2

    doc = _first_scanned_row_with_comment(rows)
    if not doc:
        print(
            f"No Instagram comment webhook in the {WEBHOOK_EVENT_SCAN_LIMIT} newest "
            f"rows in {WEBHOOK_CONTAINER}; nothing to do."
        )
        return 0

    payload = _payload_from_doc(doc)
    if not payload:
        print("Row has no parseable raw_payload/raw_body.", file=sys.stderr)
        return 0

    processor = CommentProcessor()
    if not any_comment_envelope_matches(processor, payload):
        print("No matching automation; not POSTing.")
        return 0

    body = _body_bytes_for_replay(doc, payload)
    try:
        sig = _sign_body(body)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2

    url = WEBHOOK_REPLAY_URL
    print(f"POSTing signed replay ({len(body)} bytes) to {url}")

    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )

    print(f"HTTP {r.status_code}")
    if r.text:
        print(r.text[:2000])
    return 0 if r.is_success else 1


if __name__ == "__main__":
    if os.getenv("CHECK_DB_MATCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) or (len(sys.argv) > 1 and sys.argv[1] in ("--check-db", "--db-match")):
        raise SystemExit(main_check_db())
    raise SystemExit(main())
