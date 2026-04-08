#!/usr/bin/env python3
"""
End-to-end webhook test: sends signed webhooks to local backend,
then queries Cosmos DB to verify raw payloads were saved,
and checks backend logs.

Usage:
    python test_webhook_e2e.py

Run this on your VM where the backend is running locally.
"""
import hashlib
import hmac
import json
import time
import sys
import os
import base64

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

# ─── Configuration ───────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000"
WEBHOOK_ENDPOINT = f"{BACKEND_URL}/api/v1/webhooks/instagram"
APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "241ea3f3aa2d29a97f02204e37e9927a")
IG_ACCOUNT_ID = "26088223200849607"

# Cosmos DB
COSMOS_ENDPOINT = os.getenv("AZURE_COSMOS_ENDPOINT", "https://creatrchoice.documents.azure.com:443/")
COSMOS_KEY = os.getenv("AZURE_COSMOS_KEY", "")
DB_NAME = os.getenv("DM_DATABASE_NAME", "dm_automation_db")
WEBHOOK_CONTAINER = "dm_webhook_events"

# Unique test marker so we can find our test docs
TEST_RUN_ID = f"test_{int(time.time())}"


# ─── Cosmos DB Helper ────────────────────────────────────────────

def get_cosmos_container():
    """Connect to Cosmos DB and return the webhook_events container."""
    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    db = client.get_database_client(DB_NAME)
    container = db.get_container_client(WEBHOOK_CONTAINER)
    return container


def query_webhook_events(container, since_timestamp: str):
    """Query webhook events saved after a given timestamp."""
    query = (
        "SELECT c.id, c.account_id, c.object, c.raw_payload, c.entry_count, "
        "c.received_at, c.processed "
        "FROM c WHERE c.account_id = @account_id AND c.received_at >= @since "
        "ORDER BY c.received_at DESC"
    )
    params = [
        {"name": "@account_id", "value": IG_ACCOUNT_ID},
        {"name": "@since", "value": since_timestamp},
    ]
    results = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=False))
    return results


# ─── Webhook Helpers ─────────────────────────────────────────────

def compute_signature(body: bytes, secret: str) -> str:
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


def send_webhook(payload: dict, label: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    signature = compute_signature(body, APP_SECRET)
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(WEBHOOK_ENDPOINT, content=body, headers=headers)
        return {"label": label, "status": resp.status_code, "body": resp.text, "ok": resp.status_code == 200}
    except Exception as e:
        return {"label": label, "status": 0, "body": str(e), "ok": False}


# ─── Test Payloads ───────────────────────────────────────────────

def build_comment_payload():
    return {
        "object": "instagram",
        "entry": [{
            "id": IG_ACCOUNT_ID,
            "time": int(time.time()),
            "changes": [{
                "field": "comments",
                "value": {
                    "id": f"comment_{TEST_RUN_ID}",
                    "text": f"E2E test comment [{TEST_RUN_ID}]",
                    "from": {"id": "99887766554433", "username": "test_user"},
                    "media": {"id": "media_001", "media_product_type": "FEED"}
                }
            }]
        }]
    }


def build_message_payload():
    return {
        "object": "instagram",
        "entry": [{
            "id": IG_ACCOUNT_ID,
            "time": int(time.time()),
            "messaging": [{
                "sender": {"id": "99887766554433"},
                "recipient": {"id": IG_ACCOUNT_ID},
                "timestamp": int(time.time() * 1000),
                "message": {
                    "mid": f"mid_{TEST_RUN_ID}",
                    "text": f"E2E test DM [{TEST_RUN_ID}]"
                }
            }]
        }]
    }


def build_postback_payload():
    postback_data = base64.b64encode(json.dumps({
        "automation_id": "auto_test",
        "action": "next_step",
        "next_step_id": "step_002",
    }).encode()).decode()

    return {
        "object": "instagram",
        "entry": [{
            "id": IG_ACCOUNT_ID,
            "time": int(time.time()),
            "messaging": [{
                "sender": {"id": "99887766554433"},
                "recipient": {"id": IG_ACCOUNT_ID},
                "timestamp": int(time.time() * 1000),
                "postback": {
                    "payload": postback_data,
                    "title": f"E2E Button [{TEST_RUN_ID}]"
                }
            }]
        }]
    }


def build_invalid_signature_payload():
    return {"object": "instagram", "entry": []}


def build_non_instagram_payload():
    return {"object": "page", "entry": [{"id": "12345", "time": int(time.time())}]}


# ─── Main ────────────────────────────────────────────────────────

def main():
    print(f"{'='*65}")
    print(f"  WEBHOOK E2E TEST — {TEST_RUN_ID}")
    print(f"  Backend: {BACKEND_URL}")
    print(f"  IG Account: {IG_ACCOUNT_ID}")
    print(f"{'='*65}")

    # Record timestamp before sending
    from datetime import datetime, timezone
    before_ts = datetime.now(timezone.utc).isoformat()

    # ─── PHASE 1: Send webhooks ──────────────────────────────
    print(f"\n📤 PHASE 1: Sending webhook requests...\n")

    results = []

    # Test 1: Comment
    r = send_webhook(build_comment_payload(), "Comment (changes)")
    print(f"  {'✅' if r['ok'] else '❌'} {r['label']} → HTTP {r['status']}  {r['body']}")
    results.append(r)

    # Test 2: DM
    r = send_webhook(build_message_payload(), "DM Message (messaging)")
    print(f"  {'✅' if r['ok'] else '❌'} {r['label']} → HTTP {r['status']}  {r['body']}")
    results.append(r)

    # Test 3: Postback
    r = send_webhook(build_postback_payload(), "Postback (messaging)")
    print(f"  {'✅' if r['ok'] else '❌'} {r['label']} → HTTP {r['status']}  {r['body']}")
    results.append(r)

    # Test 4: Invalid signature (expect 401)
    body = json.dumps(build_invalid_signature_payload()).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(WEBHOOK_ENDPOINT, content=body, headers=headers)
        r = {"label": "Invalid Signature", "status": resp.status_code, "body": resp.text, "ok": resp.status_code == 401}
    except Exception as e:
        r = {"label": "Invalid Signature", "status": 0, "body": str(e), "ok": False}
    print(f"  {'✅' if r['ok'] else '❌'} {r['label']} → HTTP {r['status']}  {r['body']}")
    results.append(r)

    # Test 5: Non-instagram object (expect 400)
    r2 = send_webhook(build_non_instagram_payload(), "Non-Instagram Object")
    r2["ok"] = r2["status"] == 400  # We EXPECT 400
    print(f"  {'✅' if r2['ok'] else '❌'} {r2['label']} → HTTP {r2['status']}  {r2['body']}")
    results.append(r2)

    # ─── PHASE 2: Verify DB ──────────────────────────────────
    print(f"\n📦 PHASE 2: Checking Cosmos DB for saved raw payloads...\n")

    time.sleep(2)  # Give backend a moment to write

    try:
        container = get_cosmos_container()
        saved_docs = query_webhook_events(container, before_ts)

        print(f"  Found {len(saved_docs)} webhook event(s) saved since test start\n")

        if len(saved_docs) == 0:
            print("  ❌ No documents found — raw webhook save may not be working!")
        else:
            # Check each saved doc
            found_comment = False
            found_dm = False
            found_postback = False

            for doc in saved_docs:
                raw = doc.get("raw_payload", {})
                entry = raw.get("entry", [{}])[0] if raw.get("entry") else {}

                doc_type = "unknown"
                if "changes" in entry:
                    for change in entry.get("changes", []):
                        if change.get("field") == "comments":
                            val_text = change.get("value", {}).get("text", "")
                            if TEST_RUN_ID in val_text:
                                doc_type = "comment"
                                found_comment = True
                elif "messaging" in entry:
                    for msg in entry.get("messaging", []):
                        if "message" in msg:
                            if TEST_RUN_ID in msg.get("message", {}).get("mid", ""):
                                doc_type = "dm"
                                found_dm = True
                        elif "postback" in msg:
                            if TEST_RUN_ID in msg.get("postback", {}).get("title", ""):
                                doc_type = "postback"
                                found_postback = True

                obj_type = raw.get("object", "?")
                entry_count = doc.get("entry_count", 0)
                print(f"  📄 id={doc['id'][:20]}...  type={doc_type:<10}  object={obj_type}  entries={entry_count}  at={doc.get('received_at', '?')}")

            print()
            print(f"  {'✅' if found_comment else '❌'} Comment payload saved in DB")
            print(f"  {'✅' if found_dm else '❌'} DM payload saved in DB")
            print(f"  {'✅' if found_postback else '❌'} Postback payload saved in DB")

            # Extra: show raw_payload of one doc for inspection
            if saved_docs:
                print(f"\n  📋 Sample raw_payload (first doc):")
                sample = saved_docs[0].get("raw_payload", {})
                print(f"     {json.dumps(sample, indent=2)[:500]}")

    except Exception as e:
        print(f"  ❌ Cosmos DB query failed: {e}")
        print(f"     Make sure AZURE_COSMOS_KEY is set in .env")

    # ─── PHASE 3: Summary ────────────────────────────────────
    print(f"\n{'='*65}")
    print("  SUMMARY")
    print(f"{'='*65}")

    api_passed = sum(1 for r in results if r["ok"])
    print(f"\n  API Tests:  {api_passed}/{len(results)} passed")
    for r in results:
        print(f"    {'✅' if r['ok'] else '❌'} {r['label']} → HTTP {r['status']}")

    print(f"\n  DB Verification: check output above")
    print(f"\n  💡 Also check your backend terminal for log lines like:")
    print(f"     → POST /api/v1/webhooks/instagram [client=127.0.0.1]")
    print(f"     Raw webhook saved: <uuid> for account {IG_ACCOUNT_ID}")
    print(f"     ← POST /api/v1/webhooks/instagram — 200 in Xms")


if __name__ == "__main__":
    main()
