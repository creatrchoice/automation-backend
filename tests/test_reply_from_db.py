#!/usr/bin/env python3
"""
Reads the 2 most recent webhook events from Cosmos DB,
displays the raw data, and sends a DM reply to the sender.

Usage:
    python test_reply_from_db.py
"""
import json
import os
import sys

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

# ─── Config ──────────────────────────────────────────────────────
COSMOS_ENDPOINT = os.getenv("AZURE_COSMOS_ENDPOINT", "https://creatrchoice.documents.azure.com:443/")
COSMOS_KEY = os.getenv("AZURE_COSMOS_KEY", "")
DB_NAME = os.getenv("DM_DATABASE_NAME", "dm_automation_db")
WEBHOOK_CONTAINER = "dm_webhook_events"
IG_ACCOUNTS_CONTAINER = "dm_ig_accounts"

INSTAGRAM_API_BASE = "https://graph.instagram.com/v21.0"


# ─── Step 1: Fetch recent webhooks ──────────────────────────────

def fetch_recent_webhooks(limit=5):
    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    db = client.get_database_client(DB_NAME)
    container = db.get_container_client(WEBHOOK_CONTAINER)

    query = "SELECT * FROM c ORDER BY c.received_at DESC OFFSET 0 LIMIT @limit"
    results = list(container.query_items(
        query=query,
        parameters=[{"name": "@limit", "value": limit}],
        enable_cross_partition_query=True,
    ))
    return results


def fetch_account_token(account_id: str):
    """Fetch access token for an IG account from Cosmos DB."""
    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    db = client.get_database_client(DB_NAME)
    container = db.get_container_client(IG_ACCOUNTS_CONTAINER)

    query = "SELECT c.access_token, c.ig_user_id, c.username FROM c WHERE c.ig_user_id = @ig_id"
    results = list(container.query_items(
        query=query,
        parameters=[{"name": "@ig_id", "value": account_id}],
        enable_cross_partition_query=True,
    ))
    if results:
        return results[0]
    return None


# ─── Step 2: Parse webhook data ─────────────────────────────────

def parse_webhook(doc):
    """Parse a saved webhook doc and extract event info."""
    raw = doc.get("raw_payload") or {}
    raw_body = doc.get("raw_body", "")

    # If raw_payload is None (parse failed), try parsing raw_body
    if not raw and raw_body:
        try:
            raw = json.loads(raw_body)
        except Exception:
            return {"type": "unparseable", "raw_body": raw_body[:500]}

    entries = raw.get("entry", [])
    if not entries:
        return {"type": "empty", "raw": raw}

    entry = entries[0]
    ig_account_id = entry.get("id", "unknown")

    # Check for messaging (DM)
    messaging = entry.get("messaging", [])
    if messaging:
        msg = messaging[0]
        sender_id = msg.get("sender", {}).get("id")
        recipient_id = msg.get("recipient", {}).get("id")
        message = msg.get("message", {})
        postback = msg.get("postback", {})

        if postback:
            return {
                "type": "postback",
                "ig_account_id": ig_account_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "postback_title": postback.get("title"),
                "postback_payload": postback.get("payload"),
            }
        else:
            return {
                "type": "message",
                "ig_account_id": ig_account_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "mid": message.get("mid"),
                "text": message.get("text"),
            }

    # Check for changes (comment)
    changes = entry.get("changes", [])
    if changes:
        change = changes[0]
        if change.get("field") == "comments":
            value = change.get("value", {})
            return {
                "type": "comment",
                "ig_account_id": ig_account_id,
                "comment_id": value.get("id"),
                "comment_text": value.get("text"),
                "from_id": value.get("from", {}).get("id"),
                "from_username": value.get("from", {}).get("username"),
                "media_id": value.get("media", {}).get("id"),
            }

    return {"type": "unknown", "raw": raw}


# ─── Step 3: Send DM reply ──────────────────────────────────────

def send_dm_reply(ig_account_id: str, recipient: dict, message_text: str, access_token: str):
    """
    Send a DM via Instagram API.

    recipient should be:
        {"id": "<USER_ID>"}          for regular DM
        {"comment_id": "<COMMENT_ID>"} for comment-triggered DM
    """
    url = f"{INSTAGRAM_API_BASE}/{ig_account_id}/messages"

    payload = {
        "recipient": recipient,
        "message": {"text": message_text},
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    print(f"\n  📤 Sending DM...")
    print(f"     URL: {url}")
    print(f"     Recipient: {json.dumps(recipient)}")
    print(f"     Message: {message_text}")

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        print(f"     Status: {resp.status_code}")
        print(f"     Response: {resp.text}")
        return resp.status_code == 200
    except Exception as e:
        print(f"     ERROR: {e}")
        return False


# ─── Main ────────────────────────────────────────────────────────

def main():
    print(f"{'='*65}")
    print(f"  WEBHOOK DB READER + DM REPLY TEST")
    print(f"{'='*65}")

    # Fetch recent webhooks
    print(f"\n📦 Fetching recent webhook events from Cosmos DB...\n")
    docs = fetch_recent_webhooks(limit=5)

    if not docs:
        print("  ❌ No webhook events found in DB")
        return

    print(f"  Found {len(docs)} webhook event(s)\n")

    # Parse and display each
    events = []
    for i, doc in enumerate(docs):
        parsed = parse_webhook(doc)
        events.append((doc, parsed))

        print(f"  ── Webhook #{i+1} ──────────────────────────────")
        print(f"     ID:          {doc.get('id', '?')[:30]}...")
        print(f"     Received:    {doc.get('received_at', '?')}")
        print(f"     Account ID:  {doc.get('account_id', '?')}")
        print(f"     Type:        {parsed.get('type', '?')}")

        if parsed["type"] == "message":
            print(f"     Sender:      {parsed.get('sender_id')}")
            print(f"     Text:        {parsed.get('text')}")
            print(f"     MID:         {parsed.get('mid')}")
        elif parsed["type"] == "comment":
            print(f"     From:        {parsed.get('from_username')} ({parsed.get('from_id')})")
            print(f"     Comment:     {parsed.get('comment_text')}")
            print(f"     Comment ID:  {parsed.get('comment_id')}")
            print(f"     Media ID:    {parsed.get('media_id')}")
        elif parsed["type"] == "postback":
            print(f"     Sender:      {parsed.get('sender_id')}")
            print(f"     Button:      {parsed.get('postback_title')}")

        # Show raw body snippet
        raw_body = doc.get("raw_body", "")
        if raw_body:
            print(f"     Raw body:    {raw_body[:200]}...")

        print()

    # ─── Send replies to real events ─────────────────────────
    print(f"\n{'='*65}")
    print(f"  SENDING DM REPLIES")
    print(f"{'='*65}")

    for i, (doc, parsed) in enumerate(events):
        event_type = parsed.get("type")
        ig_account_id = parsed.get("ig_account_id") or doc.get("account_id")

        if event_type not in ("message", "comment"):
            print(f"\n  ⏭️  Webhook #{i+1}: type={event_type}, skipping (not message/comment)")
            continue

        # Get access token for this IG account
        print(f"\n  🔑 Webhook #{i+1}: Looking up access token for IG account {ig_account_id}...")
        account = fetch_account_token(ig_account_id)

        if not account:
            print(f"     ❌ No account found in DB for IG ID {ig_account_id}")
            print(f"     Trying with account_id from doc: {doc.get('account_id')}")
            account = fetch_account_token(doc.get("account_id", ""))

        if not account:
            print(f"     ❌ Still no account found. Skipping.")
            continue

        access_token = account.get("access_token")
        print(f"     ✅ Found account: {account.get('username')} (token: {access_token[:20]}...)")

        if event_type == "comment":
            # Reply to commenter via comment_id (Instagram requirement)
            comment_id = parsed.get("comment_id")
            if not comment_id:
                print(f"     ❌ No comment_id found, can't reply")
                continue

            send_dm_reply(
                ig_account_id=ig_account_id,
                recipient={"comment_id": comment_id},
                message_text="Hey! Thanks for your comment 🙌 This is an automated test reply.",
                access_token=access_token,
            )

        elif event_type == "message":
            # Reply to DM sender via user ID
            sender_id = parsed.get("sender_id")
            if not sender_id:
                print(f"     ❌ No sender_id found, can't reply")
                continue

            send_dm_reply(
                ig_account_id=ig_account_id,
                recipient={"id": sender_id},
                message_text="Hey! Got your message. This is an automated test reply ✌️",
                access_token=access_token,
            )

    print(f"\n{'='*65}")
    print(f"  DONE")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
