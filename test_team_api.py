"""
End-to-end test for the Team / Organization feature.

Uses FastAPI TestClient (in-process) with mocked Cosmos DB and Redis
so we can verify the full flow without external services.
"""
import os
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Set env before any imports
os.environ["RESEND_API_KEY"] = "re_test_key"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-local-testing"
os.environ["FRONTEND_URL"] = "http://localhost:5173"
os.environ["EMAIL_FROM_NAME"] = "Sharda"
os.environ["EMAIL_FROM_ADDRESS"] = "sharda@creatrchoice.info"

import jwt
from fastapi.testclient import TestClient


# ─── In-memory Cosmos mock ──────────────────────────────────────────────────

class InMemoryContainer:
    """Simple in-memory mock for Cosmos DB container."""

    def __init__(self):
        self.items = {}

    async def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
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

    async def delete_item(self, item, partition_key):
        self.items.pop(item, None)

    async def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False):
        """Very simple query matcher — just filter by parameter values."""
        param_map = {}
        for p in (parameters or []):
            param_map[p["name"]] = p["value"]

        for item in list(self.items.values()):
            match = True
            for pname, pval in param_map.items():
                clean_name = pname.lstrip("@")

                # Handle JOIN queries (search inside members array)
                if "JOIN" in query.upper() and clean_name in ("user_id", "uid"):
                    members = item.get("members", [])
                    found = any(m.get("user_id") == pval for m in members)
                    if not found:
                        match = False
                elif clean_name == "token":
                    if item.get("id") != pval:
                        match = False
                elif clean_name == "account_id":
                    if item.get("id") != pval:
                        match = False
                elif clean_name == "org_id":
                    if item.get("org_id") != pval:
                        match = False
                elif clean_name == "email":
                    if item.get("email", "").lower() != pval.lower():
                        match = False

            # Check status filter in query
            if "status = 'pending'" in query.lower():
                if item.get("status") != "pending":
                    match = False

            if match:
                yield json.loads(json.dumps(item))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


# Global container storage
_containers = {}

def get_container(name):
    if name not in _containers:
        _containers[name] = InMemoryContainer()
    return _containers[name]


class MockCosmosClient:
    async def get_async_container_client(self, name):
        return get_container(name)


class MockRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)


# ─── Override dependencies ──────────────────────────────────────────────────

mock_cosmos = MockCosmosClient()
mock_redis = MockRedis()

from app.api.deps import get_cosmos_client, get_redis_client

# Patch at module level for deps
import app.api.deps as deps_module

original_get_cosmos = deps_module.get_cosmos_client
original_get_redis = deps_module.get_redis_client


async def mock_get_cosmos():
    return mock_cosmos

async def mock_get_redis():
    return mock_redis


# Now import the app
from main import app

app.dependency_overrides[get_cosmos_client] = mock_get_cosmos
app.dependency_overrides[get_redis_client] = mock_get_redis

client = TestClient(app)


# ─── Test helpers ───────────────────────────────────────────────────────────

def make_token(user_id, email, org_id=None):
    from app.api.deps import create_access_token
    from datetime import timedelta
    data = {"sub": user_id, "email": email}
    if org_id:
        data["org_id"] = org_id
    return create_access_token(data=data, expires_delta=timedelta(hours=1))


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ─── Tests ──────────────────────────────────────────────────────────────────

def test_full_team_flow():
    print("\n" + "=" * 60)
    print("TEAM / ORGANIZATION E2E TEST")
    print("=" * 60)

    # 1. Create a user (simulate by creating user doc directly)
    owner_id = "pankaj_supanote_ai"
    owner_email = "pankaj@supanote.ai"
    owner_token = make_token(owner_id, owner_email)

    print(f"\n1. Owner: {owner_email} (no org yet)")

    # 2. Create organization
    print("\n2. Creating organization 'CreatrChoice Team'...")
    resp = client.post(
        "/api/v1/team/org?name=CreatrChoice%20Team",
        headers=auth_header(owner_token),
    )
    print(f"   Status: {resp.status_code}")
    data = resp.json()
    print(f"   Response: {json.dumps(data, indent=2)}")
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert data["organization"]["name"] == "CreatrChoice Team"

    org_id = data["organization"]["id"]
    new_owner_token = data["access_token"]
    print(f"   ✓ Org created: {org_id}")

    # Verify JWT contains org_id
    decoded = jwt.decode(new_owner_token, "test-secret-key-for-local-testing", algorithms=["HS256"])
    assert decoded["org_id"] == org_id
    print(f"   ✓ JWT contains org_id")

    # 3. Get organization
    print("\n3. Getting organization...")
    resp = client.get("/api/v1/team/org", headers=auth_header(new_owner_token))
    print(f"   Status: {resp.status_code}")
    assert resp.status_code == 200
    print(f"   ✓ Got org: {resp.json()['organization']['name']}")

    # 4. List members (should have 1 - the owner)
    print("\n4. Listing members...")
    resp = client.get("/api/v1/team/members", headers=auth_header(new_owner_token))
    assert resp.status_code == 200
    members = resp.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "owner"
    print(f"   ✓ Members: {json.dumps(members, indent=2)}")

    # 5. Invite a member (mock email sending)
    print("\n5. Inviting editor@example.com as editor...")
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = {"id": "resend_test_123"}
        resp = client.post(
            "/api/v1/team/invite?email=editor@example.com&role=editor",
            headers=auth_header(new_owner_token),
        )
    print(f"   Status: {resp.status_code}")
    data = resp.json()
    print(f"   Response: {json.dumps(data, indent=2)}")
    assert resp.status_code == 201
    assert data["email_sent"] is True
    invite_token = data["token"]
    print(f"   ✓ Invite sent, token: {invite_token[:20]}...")

    # 6. Validate invite token (public endpoint)
    print("\n6. Validating invite token (public)...")
    resp = client.get(f"/api/v1/team/invite/{invite_token}")
    assert resp.status_code == 200
    info = resp.json()
    assert info["valid"] is True
    assert info["role"] == "editor"
    assert info["org_name"] == "CreatrChoice Team"
    print(f"   ✓ Invite valid: {json.dumps(info, indent=2)}")

    # 7. Accept invite (as the invited user)
    editor_id = "editor_example_com"
    editor_email = "editor@example.com"
    editor_token = make_token(editor_id, editor_email)

    print(f"\n7. Accepting invite as {editor_email}...")
    resp = client.post(
        f"/api/v1/team/invite/accept?token={invite_token}",
        headers=auth_header(editor_token),
    )
    print(f"   Status: {resp.status_code}")
    data = resp.json()
    print(f"   Response: {json.dumps(data, indent=2)}")
    assert resp.status_code == 200
    assert data["role"] == "editor"
    editor_org_token = data["access_token"]

    decoded = jwt.decode(editor_org_token, "test-secret-key-for-local-testing", algorithms=["HS256"])
    assert decoded["org_id"] == org_id
    print(f"   ✓ Editor joined org, JWT has org_id")

    # 8. List members (should now have 2)
    print("\n8. Listing members (should be 2)...")
    resp = client.get("/api/v1/team/members", headers=auth_header(new_owner_token))
    members = resp.json()["members"]
    assert len(members) == 2
    print(f"   ✓ {len(members)} members:")
    for m in members:
        print(f"     - {m['email']}: {m['role']}")

    # 9. Invite a viewer
    print("\n9. Inviting viewer@example.com as viewer...")
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock) as mock_email:
        mock_email.return_value = {"id": "resend_test_456"}
        resp = client.post(
            "/api/v1/team/invite?email=viewer@example.com&role=viewer",
            headers=auth_header(new_owner_token),
        )
    assert resp.status_code == 201
    viewer_invite_token = resp.json()["token"]

    viewer_id = "viewer_example_com"
    viewer_email = "viewer@example.com"
    viewer_token = make_token(viewer_id, viewer_email)

    resp = client.post(
        f"/api/v1/team/invite/accept?token={viewer_invite_token}",
        headers=auth_header(viewer_token),
    )
    assert resp.status_code == 200
    viewer_org_token = resp.json()["access_token"]
    print(f"   ✓ Viewer joined")

    # 10. Permission tests
    print("\n10. Testing permissions...")

    # Editor cannot invite (needs admin)
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock):
        resp = client.post(
            "/api/v1/team/invite?email=another@example.com&role=viewer",
            headers=auth_header(editor_org_token),
        )
    assert resp.status_code == 403
    print(f"   ✓ Editor cannot invite (403): {resp.json()['error']['message']}")

    # Viewer cannot invite
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock):
        resp = client.post(
            "/api/v1/team/invite?email=another@example.com&role=viewer",
            headers=auth_header(viewer_org_token),
        )
    assert resp.status_code == 403
    print(f"   ✓ Viewer cannot invite (403)")

    # Viewer can view members
    resp = client.get("/api/v1/team/members", headers=auth_header(viewer_org_token))
    assert resp.status_code == 200
    print(f"   ✓ Viewer can list members (200)")

    # 11. Update role
    print("\n11. Updating editor to admin...")
    resp = client.patch(
        f"/api/v1/team/members/{editor_id}?role=admin",
        headers=auth_header(new_owner_token),
    )
    assert resp.status_code == 200
    assert resp.json()["member"]["role"] == "admin"
    print(f"   ✓ Editor promoted to admin")

    # 12. Admin can't change owner's role
    print("\n12. Testing role protections...")
    # Need a fresh token for editor with org_id
    editor_admin_token = make_token(editor_id, editor_email, org_id)

    resp = client.patch(
        f"/api/v1/team/members/{owner_id}?role=viewer",
        headers=auth_header(editor_admin_token),
    )
    assert resp.status_code == 403
    print(f"   ✓ Admin cannot change owner's role (403)")

    # 13. Cannot invite as owner
    print("\n13. Testing owner invite protection...")
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock):
        resp = client.post(
            "/api/v1/team/invite?email=hack@example.com&role=owner",
            headers=auth_header(new_owner_token),
        )
    assert resp.status_code == 403
    print(f"   ✓ Cannot invite as owner (403)")

    # 14. Remove a member
    print("\n14. Removing viewer...")
    resp = client.delete(
        f"/api/v1/team/members/{viewer_id}",
        headers=auth_header(new_owner_token),
    )
    assert resp.status_code == 200
    print(f"   ✓ Viewer removed")

    # Verify 2 members left
    resp = client.get("/api/v1/team/members", headers=auth_header(new_owner_token))
    members = resp.json()["members"]
    assert len(members) == 2
    print(f"   ✓ {len(members)} members remaining")

    # 15. Cannot remove owner
    print("\n15. Testing owner removal protection...")
    resp = client.delete(
        f"/api/v1/team/members/{owner_id}",
        headers=auth_header(editor_admin_token),
    )
    assert resp.status_code == 403
    print(f"   ✓ Cannot remove owner (403)")

    # 16. Duplicate invite check
    print("\n16. Testing duplicate invite protection...")
    with patch("app.api.team.send_invitation_email", new_callable=AsyncMock):
        resp = client.post(
            "/api/v1/team/invite?email=editor@example.com&role=viewer",
            headers=auth_header(new_owner_token),
        )
    assert resp.status_code == 409
    print(f"   ✓ Cannot invite existing member (409)")

    # 17. Duplicate org creation check
    print("\n17. Testing duplicate org protection...")
    resp = client.post(
        "/api/v1/team/org?name=Another%20Org",
        headers=auth_header(new_owner_token),
    )
    assert resp.status_code == 409
    print(f"   ✓ Cannot create second org (409)")

    # 18. Invalid invite token
    print("\n18. Testing invalid invite token...")
    resp = client.get("/api/v1/team/invite/invalid-token-xyz")
    assert resp.status_code == 404
    print(f"   ✓ Invalid token returns 404")

    # 19. Delete organization (owner only)
    print("\n19. Testing org deletion...")
    # Admin can't delete
    resp = client.delete("/api/v1/team/org", headers=auth_header(editor_admin_token))
    assert resp.status_code == 403
    print(f"   ✓ Admin cannot delete org (403)")

    # Owner can delete
    resp = client.delete("/api/v1/team/org", headers=auth_header(new_owner_token))
    assert resp.status_code == 200
    print(f"   ✓ Owner deleted org (200)")

    print("\n" + "=" * 60)
    print("ALL 19 TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    test_full_team_flow()
