"""
Comprehensive E2E test for ALL APIs.

Uses FastAPI TestClient with mocked Cosmos DB and Redis.
Tests: Auth, Accounts, Automations, Contacts, Analytics, Webhooks, Team, Media.
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import os
import json
import uuid
import hashlib
import hmac
import re
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

# Set env BEFORE any app imports
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-e2e"
os.environ["INSTAGRAM_APP_ID"] = "1234567890"
os.environ["INSTAGRAM_APP_SECRET"] = "test_app_secret"
os.environ["INSTAGRAM_REDIRECT_URI"] = "http://localhost:8000/auth/instagram/callback"
os.environ["WEBHOOK_VERIFY_TOKEN"] = "test_verify_token"
os.environ["RESEND_API_KEY"] = "re_test"
os.environ["FRONTEND_URL"] = "http://localhost:5173"
os.environ["EMAIL_FROM_NAME"] = "Test"
os.environ["EMAIL_FROM_ADDRESS"] = "test@test.com"
os.environ["AZURE_SERVICE_BUS_CONNECTION_STRING"] = ""
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_PORT"] = "6379"
os.environ["REDIS_PASSWORD"] = ""
os.environ["REDIS_SSL"] = "false"

import jwt as pyjwt
from fastapi.testclient import TestClient


# ─── In-memory Cosmos mock ──────────────────────────────────────────────────

class InMemoryContainer:
    """In-memory mock for Cosmos DB container with query support."""

    def __init__(self):
        self.items = {}

    async def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            from azure.cosmos.exceptions import CosmosResourceExistsError
            raise Exception(f"Item {item_id} already exists (409)")
        self.items[item_id] = json.loads(json.dumps(body))
        return self.items[item_id]

    async def upsert_item(self, body):
        item_id = body["id"]
        self.items[item_id] = json.loads(json.dumps(body))
        return self.items[item_id]

    async def read_item(self, item, partition_key):
        if item in self.items:
            return json.loads(json.dumps(self.items[item]))
        raise Exception(f"Item {item} not found (404)")

    async def replace_item(self, item, body, partition_key=None):
        item_id = item if isinstance(item, str) else item["id"]
        self.items[item_id] = json.loads(json.dumps(body))
        return self.items[item_id]

    async def delete_item(self, item, partition_key=None):
        self.items.pop(item, None)

    async def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False):
        """Simple query matcher by parameter values."""
        param_map = {}
        for p in (parameters or []):
            param_map[p["name"]] = p["value"]

        query_lower = query.lower()

        for item in list(self.items.values()):
            match = True
            for pname, pval in param_map.items():
                clean_name = pname.lstrip("@")

                # Handle JOIN queries (members array)
                if "join" in query_lower and clean_name in ("user_id", "uid"):
                    members = item.get("members", [])
                    found = any(m.get("user_id") == pval for m in members)
                    if not found:
                        match = False
                elif clean_name == "email":
                    if item.get("email", "").lower() != pval.lower():
                        match = False
                elif clean_name == "account_id":
                    if item.get("account_id") != pval and item.get("id") != pval:
                        match = False
                elif clean_name == "automation_id":
                    if item.get("id") != pval:
                        match = False
                elif clean_name == "contact_id":
                    if item.get("id") != pval:
                        match = False
                elif clean_name == "user_id":
                    if item.get("user_id") != pval:
                        match = False
                elif clean_name == "token":
                    if item.get("id") != pval:
                        match = False
                elif clean_name == "org_id":
                    if item.get("org_id") != pval:
                        match = False
                else:
                    if item.get(clean_name) != pval:
                        match = False

            # Status filters
            if "status = 'active'" in query_lower:
                if item.get("status") != "active":
                    match = False
            if "status = 'pending'" in query_lower:
                if item.get("status") != "pending":
                    match = False

            if match:
                yield json.loads(json.dumps(item))


# Global container storage
_containers = {}


def get_container(name):
    if name not in _containers:
        _containers[name] = InMemoryContainer()
    return _containers[name]


def reset_containers():
    _containers.clear()


class MockCosmosClient:
    async def get_async_container_client(self, name):
        return get_container(name)


class MockRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        val = self.store.get(key)
        if isinstance(val, str):
            return val.encode() if not isinstance(val, bytes) else val
        return val

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def exists(self, key):
        return key in self.store


# ─── Override dependencies ──────────────────────────────────────────────────

mock_cosmos = MockCosmosClient()
mock_redis = MockRedis()

from app.api.deps import get_cosmos_client, get_redis_client
from main import app

app.dependency_overrides[get_cosmos_client] = lambda: mock_cosmos
app.dependency_overrides[get_redis_client] = lambda: mock_redis

# Use async overrides
async def mock_get_cosmos():
    return mock_cosmos

async def mock_get_redis():
    return mock_redis

app.dependency_overrides[get_cosmos_client] = mock_get_cosmos
app.dependency_overrides[get_redis_client] = mock_get_redis

client = TestClient(app)


# ─── Helpers ────────────────────────────────────────────────────────────────

def make_token(user_id, email, org_id=None):
    from app.api.deps import create_access_token
    data = {"sub": user_id, "email": email}
    if org_id:
        data["org_id"] = org_id
    return create_access_token(data=data, expires_delta=timedelta(hours=1))


def auth(token):
    return {"Authorization": f"Bearer {token}"}


PASS = 0
FAIL = 0


def check(test_name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {test_name}")
    else:
        FAIL += 1
        print(f"  ✗ {test_name} — {detail}")


# ─── 1. AUTH TESTS ──────────────────────────────────────────────────────────

def test_auth():
    print("\n" + "=" * 60)
    print("1. AUTH API TESTS")
    print("=" * 60)

    # 1a. Signup
    r = client.post("/api/v1/auth/signup", params={"email": "testuser@example.com", "password": "password123"})
    check("Signup returns 201", r.status_code == 201, f"got {r.status_code}: {r.text}")
    data = r.json()
    check("Signup returns access_token", "access_token" in data, str(data))
    check("Signup returns user_id", "user_id" in data, str(data))
    check("Signup auto-creates org", "org_id" in data and data["org_id"] is not None, str(data))
    user_id = data["user_id"]
    org_id = data["org_id"]
    token = data["access_token"]

    # 1b. Duplicate signup
    r = client.post("/api/v1/auth/signup", params={"email": "testuser@example.com", "password": "password123"})
    check("Duplicate signup returns 409", r.status_code == 409, f"got {r.status_code}")

    # 1c. Signup with weak password
    r = client.post("/api/v1/auth/signup", params={"email": "weak@test.com", "password": "123"})
    check("Weak password returns 400", r.status_code == 400, f"got {r.status_code}")

    # 1d. Login
    r = client.post("/api/v1/auth/login", params={"email": "testuser@example.com", "password": "password123"})
    check("Login returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    login_data = r.json()
    check("Login returns token", "access_token" in login_data)
    check("Login returns org_id", login_data.get("org_id") == org_id, f"expected {org_id}, got {login_data.get('org_id')}")

    # 1e. Wrong password
    r = client.post("/api/v1/auth/login", params={"email": "testuser@example.com", "password": "wrongpass"})
    check("Wrong password returns 401", r.status_code == 401, f"got {r.status_code}")

    # 1f. Non-existent user
    r = client.post("/api/v1/auth/login", params={"email": "nobody@test.com", "password": "password123"})
    check("Non-existent user returns 401", r.status_code == 401, f"got {r.status_code}")

    # 1g. Protected route without token
    r = client.get("/api/v1/accounts")
    check("No-token request returns 401", r.status_code == 401, f"got {r.status_code}")

    return user_id, org_id, token


# ─── 2. ACCOUNTS TESTS ─────────────────────────────────────────────────────

def test_accounts(user_id, token):
    print("\n" + "=" * 60)
    print("2. ACCOUNTS API TESTS")
    print("=" * 60)

    # 2a. List accounts (empty)
    r = client.get("/api/v1/accounts", headers=auth(token))
    check("List accounts returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    data = r.json()
    check("Empty accounts list", data.get("total") == 0, f"got total={data.get('total')}")

    # 2b. Seed an IG account directly in the mock DB
    import asyncio
    account_doc = {
        "id": "instagram_111222333",
        "user_id": user_id,
        "type": "instagram_account",
        "ig_user_id": "111222333",
        "username": "test_creator",
        "name": "Test Creator",
        "account_type": "BUSINESS",
        "profile_picture_url": "https://example.com/pic.jpg",
        "followers_count": 500,
        "access_token": "IGQVJ_test_long_lived_token",
        "token_expires_in": 5184000,
        "status": "active",
        "created_at": None,
        "updated_at": None,
    }
    from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS
    container = get_container(CONTAINER_IG_ACCOUNTS)
    asyncio.get_event_loop().run_until_complete(container.upsert_item(account_doc))

    # 2c. List accounts (should have 1 now)
    r = client.get("/api/v1/accounts", headers=auth(token))
    data = r.json()
    accounts = data.get("accounts", [])
    check("List accounts returns 1 account", len(accounts) == 1, f"got {len(accounts)} accounts")
    check("Account username matches", accounts[0]["username"] == "test_creator" if accounts else False)

    # 2d. Get single account
    r = client.get("/api/v1/accounts/instagram_111222333", headers=auth(token))
    check("Get single account returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    return "instagram_111222333"


# ─── 3. AUTOMATIONS TESTS ──────────────────────────────────────────────────

def test_automations(user_id, token, account_id):
    print("\n" + "=" * 60)
    print("3. AUTOMATIONS API TESTS")
    print("=" * 60)

    # 3a. Create automation
    r = client.post(
        "/api/v1/automations",
        params={
            "account_id": account_id,
            "name": "Welcome DM",
        },
        json={
            "trigger": {"type": "message_received", "keywords": ["hello", "hi"]},
            "conditions": [],
            "steps": [{"type": "send_message", "message": "Welcome! Thanks for reaching out."}],
        },
        headers=auth(token),
    )
    # The endpoint takes trigger as query param, let me check the actual signature
    # Actually, from reading the code, it takes them as body params since they're Dict types
    # FastAPI puts non-simple types in body. Let me adjust.
    check("Create automation returns 201", r.status_code == 201, f"got {r.status_code}: {r.text}")

    if r.status_code == 201:
        automation = r.json()
        automation_id = automation.get("id")
        check("Automation has id", automation_id is not None)
        check("Automation name matches", automation.get("name") == "Welcome DM")
        check("Automation status is active", automation.get("status") == "active")
    else:
        # Fallback: seed automation manually
        automation_id = f"auto_{uuid.uuid4().hex[:8]}"
        auto_doc = {
            "id": automation_id,
            "user_id": user_id,
            "account_id": account_id,
            "name": "Welcome DM",
            "trigger": {"type": "message_received", "keywords": ["hello"]},
            "conditions": [],
            "steps": [{"type": "send_message", "message": "Welcome!"}],
            "status": "active",
            "enabled": True,
            "created_at": None,
            "updated_at": None,
        }
        import asyncio
        from app.db.cosmos_containers import CONTAINER_AUTOMATIONS
        container = get_container(CONTAINER_AUTOMATIONS)
        asyncio.get_event_loop().run_until_complete(container.upsert_item(auto_doc))
        print(f"  ℹ Seeded automation manually: {automation_id}")

    # 3b. List automations
    r = client.get(f"/api/v1/automations?account_id={account_id}", headers=auth(token))
    check("List automations returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 3c. Get single automation
    r = client.get(f"/api/v1/automations/{automation_id}", headers=auth(token))
    check("Get automation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 3d. Update automation status
    r = client.patch(
        f"/api/v1/automations/{automation_id}/status?status_value=paused",
        headers=auth(token),
    )
    check("Pause automation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    if r.status_code == 200:
        check("Automation is paused", r.json().get("status") == "paused")

    # 3e. Re-activate
    r = client.patch(
        f"/api/v1/automations/{automation_id}/status?status_value=active",
        headers=auth(token),
    )
    check("Reactivate automation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    return automation_id


# ─── 4. CONTACTS TESTS ─────────────────────────────────────────────────────

def test_contacts(user_id, token, account_id):
    print("\n" + "=" * 60)
    print("4. CONTACTS API TESTS")
    print("=" * 60)

    # Seed a contact
    import asyncio
    from app.db.cosmos_containers import CONTAINER_CONTACTS
    contact_id = str(uuid.uuid4())
    contact_doc = {
        "id": contact_id,
        "account_id": account_id,
        "ig_user_id": "999888777",
        "ig_username": "fan_user",
        "ig_name": "Fan User",
        "tags": ["vip"],
        "interaction_count": 5,
        "last_message_sent_at": None,
        "last_message_received_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    container = get_container(CONTAINER_CONTACTS)
    asyncio.get_event_loop().run_until_complete(container.upsert_item(contact_doc))

    # 4a. List contacts
    r = client.get(f"/api/v1/contacts?account_id={account_id}", headers=auth(token))
    check("List contacts returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 4b. Get single contact
    r = client.get(f"/api/v1/contacts/{contact_id}?account_id={account_id}", headers=auth(token))
    check("Get contact returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 4c. Update tags (add_tags and remove_tags are query params)
    r = client.patch(
        f"/api/v1/contacts/{contact_id}/tags?account_id={account_id}&add_tags=lead&add_tags=hot",
        headers=auth(token),
    )
    check("Update tags returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    if r.status_code == 200:
        tags = r.json().get("tags", [])
        check("Tags include 'lead'", "lead" in tags, f"tags={tags}")
        check("Tags include 'vip' (kept)", "vip" in tags, f"tags={tags}")

    return contact_id


# ─── 5. ANALYTICS TESTS ────────────────────────────────────────────────────

def test_analytics(token, account_id):
    print("\n" + "=" * 60)
    print("5. ANALYTICS API TESTS")
    print("=" * 60)

    # 5a. Overview
    r = client.get(f"/api/v1/analytics/overview?account_id={account_id}", headers=auth(token))
    check("Analytics overview returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 5b. Daily stats (requires start_date and end_date)
    from datetime import date
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    r = client.get(f"/api/v1/analytics/daily?account_id={account_id}&start_date={week_ago}&end_date={today}", headers=auth(token))
    check("Analytics daily returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")


# ─── 6. WEBHOOKS TESTS ─────────────────────────────────────────────────────

def test_webhooks():
    print("\n" + "=" * 60)
    print("6. WEBHOOKS API TESTS")
    print("=" * 60)

    # 6a. Webhook verification (GET) - correct token
    r = client.get(
        "/api/v1/webhooks/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "1234567890",
        },
    )
    check("Webhook verify returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    check("Webhook verify returns challenge", r.text == "1234567890", f"got: {r.text}")

    # 6b. Wrong verify token
    r = client.get(
        "/api/v1/webhooks/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "123",
        },
    )
    check("Wrong verify token returns 403", r.status_code == 403, f"got {r.status_code}")

    # 6c. Webhook POST with valid signature
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "111222333",
                "time": 1234567890,
                "messaging": [
                    {
                        "sender": {"id": "999888777"},
                        "recipient": {"id": "111222333"},
                        "timestamp": 1234567890000,
                        "message": {
                            "mid": "msg_001",
                            "text": "Hello there!",
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    sig = hmac.new(b"test_app_secret", body, hashlib.sha256).hexdigest()

    r = client.post(
        "/api/v1/webhooks/instagram",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    check("Webhook POST returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    check("Webhook returns EVENT_RECEIVED", r.json().get("status") == "EVENT_RECEIVED")

    # 6d. Verify raw payload was saved to DB
    import asyncio
    from app.db.cosmos_containers import CONTAINER_WEBHOOK_EVENTS
    container = get_container(CONTAINER_WEBHOOK_EVENTS)
    saved_count = len(container.items)
    check("Raw webhook saved to DB", saved_count >= 1, f"saved_count={saved_count}")

    if saved_count > 0:
        saved = list(container.items.values())[0]
        check("Saved webhook has account_id", saved.get("account_id") == "111222333", f"got {saved.get('account_id')}")
        check("Saved webhook has raw_payload", "entry" in saved.get("raw_payload", {}))
        check("Saved webhook has received_at", saved.get("received_at") is not None)

    # 6e. Webhook POST with invalid signature
    r = client.post(
        "/api/v1/webhooks/instagram",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalid_signature",
        },
    )
    check("Invalid signature returns 401", r.status_code == 401, f"got {r.status_code}")

    # 6f. Webhook POST with missing signature
    r = client.post(
        "/api/v1/webhooks/instagram",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    check("Missing signature returns 401", r.status_code == 401, f"got {r.status_code}")


# ─── 7. TEAM / ORG TESTS ───────────────────────────────────────────────────

def test_team(user_id, org_id, token):
    print("\n" + "=" * 60)
    print("7. TEAM / ORG API TESTS")
    print("=" * 60)

    # 7a. Get org (response shape: {"organization": {...}})
    r = client.get("/api/v1/team/org", headers=auth(token))
    check("Get org returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    if r.status_code == 200:
        org_data = r.json().get("organization")
        check("Org data is present", org_data is not None, f"got {r.json()}")

    # 7b. List members
    r = client.get("/api/v1/team/members", headers=auth(token))
    check("List members returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")
    if r.status_code == 200:
        members = r.json().get("members", [])
        check("Has 1 member (owner)", len(members) == 1, f"got {len(members)}")

    # 7c. Invite a team member (email and role are query params)
    with patch("app.services.email_service.send_invitation_email", new_callable=AsyncMock, return_value=True):
        r = client.post(
            "/api/v1/team/invite?email=editor@example.com&role=editor",
            headers=auth(token),
        )
    check("Invite returns 201", r.status_code == 201, f"got {r.status_code}: {r.text}")

    invite_token = None
    if r.status_code == 201:
        invite_data = r.json()
        # Extract token from invite_link or from the response
        invite_link = invite_data.get("invite_link", "")
        if "token=" in invite_link:
            invite_token = invite_link.split("token=")[-1]
        else:
            invite_token = invite_data.get("token")
        check("Invite has token", invite_token is not None, str(invite_data))

    # 7d. List pending invites
    r = client.get("/api/v1/team/invites", headers=auth(token))
    check("List invites returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 7e. Validate invite token
    if invite_token:
        r = client.get(f"/api/v1/team/invite/{invite_token}")
        check("Validate invite returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 7f. Accept invite (simulate new user)
    if invite_token:
        # Create the editor user (signup auto-creates an org)
        r = client.post("/api/v1/auth/signup", params={"email": "editor@example.com", "password": "password123"})
        editor_data = r.json()
        editor_token = editor_data.get("access_token")
        editor_org_id = editor_data.get("org_id")

        # Delete the auto-created org so editor can accept invite to our org
        if editor_org_id:
            import asyncio
            from app.db.cosmos_containers import CONTAINER_ORGANIZATIONS
            org_container = get_container(CONTAINER_ORGANIZATIONS)
            asyncio.get_event_loop().run_until_complete(
                org_container.delete_item(editor_org_id, partition_key=editor_org_id)
            )

        # Re-create token WITHOUT org_id (simulating user without an org)
        editor_token_no_org = make_token("editor_example_com", "editor@example.com")

        r = client.post(
            f"/api/v1/team/invite/accept?token={invite_token}",
            headers=auth(editor_token_no_org),
        )
        check("Accept invite returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

    # 7g. List members again (should have 2)
    r = client.get("/api/v1/team/members", headers=auth(token))
    if r.status_code == 200:
        members = r.json().get("members", [])
        check("Now has 2 members", len(members) == 2, f"got {len(members)}")


# ─── 8. WEBHOOK SUBSCRIPTION ENDPOINT TEST ─────────────────────────────────

def test_webhook_subscription(user_id, token, account_id):
    print("\n" + "=" * 60)
    print("8. WEBHOOK SUBSCRIPTION ENDPOINT TESTS")
    print("=" * 60)

    # 8a. Mock the _subscribe_webhook_events helper directly
    with patch("app.api.auth._subscribe_webhook_events", new_callable=AsyncMock, return_value=True):
        r = client.post(
            f"/api/v1/auth/instagram/{account_id}/subscribe-webhooks",
            headers=auth(token),
        )
        check("Subscribe webhooks returns 200", r.status_code == 200, f"got {r.status_code}: {r.text}")

        if r.status_code == 200:
            data = r.json()
            check("Status is subscribed", data.get("status") == "subscribed")
            check("Webhook fields returned", data.get("webhook_fields") == ["messages", "messaging_postbacks", "comments"])

    # 8b. Verify account in DB has webhook_subscribed flag
    import asyncio
    from app.db.cosmos_containers import CONTAINER_IG_ACCOUNTS
    container = get_container(CONTAINER_IG_ACCOUNTS)
    account = asyncio.get_event_loop().run_until_complete(
        container.read_item(account_id, partition_key=user_id)
    )
    check("Account has webhook_subscribed=True", account.get("webhook_subscribed") == True)
    check("Account has webhook_fields", account.get("webhook_fields") == ["messages", "messaging_postbacks", "comments"])

    # 8c. Non-existent account
    r = client.post(
        "/api/v1/auth/instagram/instagram_nonexistent/subscribe-webhooks",
        headers=auth(token),
    )
    check("Non-existent account returns 400", r.status_code == 400, f"got {r.status_code}")


# ─── 9. REQUEST LOGGING MIDDLEWARE TEST ─────────────────────────────────────

def test_logging_middleware():
    print("\n" + "=" * 60)
    print("9. LOGGING MIDDLEWARE TESTS")
    print("=" * 60)

    # Health endpoint
    r = client.get("/health")
    check("Health returns 200", r.status_code == 200, f"got {r.status_code}")
    check("Health returns healthy", r.json().get("status") == "healthy")

    # Root endpoint
    r = client.get("/")
    check("Root returns 200", r.status_code == 200)
    check("Root has service name", "Instagram DM Automation" in r.json().get("service", ""))


# ─── 10. ERROR FORMAT TESTS ────────────────────────────────────────────────

def test_error_format():
    print("\n" + "=" * 60)
    print("10. ERROR FORMAT CONSISTENCY TESTS")
    print("=" * 60)

    # All errors should return { error: { code, title, message } }
    r = client.post("/api/v1/auth/login", params={"email": "nobody@test.com", "password": "wrong"})
    data = r.json()
    check("Error has 'error' key", "error" in data, str(data))
    if "error" in data:
        err = data["error"]
        check("Error has 'code'", "code" in err)
        check("Error has 'title'", "title" in err)
        check("Error has 'message'", "message" in err)

    # No-auth error
    r = client.get("/api/v1/accounts")
    data = r.json()
    check("401 has error format", "error" in data, str(data))


# ─── RUN ALL ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "█" * 60)
    print("  COMPREHENSIVE API E2E TEST SUITE")
    print("█" * 60)

    # Reset state
    reset_containers()

    # Run tests in order (they build on each other)
    user_id, org_id, token = test_auth()
    account_id = test_accounts(user_id, token)
    automation_id = test_automations(user_id, token, account_id)
    contact_id = test_contacts(user_id, token, account_id)
    test_analytics(token, account_id)
    test_webhooks()
    test_team(user_id, org_id, token)
    test_webhook_subscription(user_id, token, account_id)
    test_logging_middleware()
    test_error_format()

    # Summary
    total = PASS + FAIL
    print("\n" + "█" * 60)
    print(f"  RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("█" * 60)

    if FAIL > 0:
        print("\n  ⚠ Some tests failed! Review output above.")
        exit(1)
    else:
        print("\n  ✓ All tests passed!")
        exit(0)
