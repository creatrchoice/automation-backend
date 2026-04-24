#!/usr/bin/env python3
"""
Test script to send signed webhook payloads to the deployed backend.
Tests both comment and message webhook formats.

Usage:
    python test_webhook_live.py

Requirements:
    pip install httpx
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="Manual live integration script; excluded from automated CI tests."
)

import hashlib
import hmac
import json
import time
import sys

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

# ─── Configuration ───────────────────────────────────────────────
BACKEND_URL = "http://localhost:8000"
WEBHOOK_ENDPOINT = f"{BACKEND_URL}/api/v1/webhooks/instagram"
APP_SECRET = "241ea3f3aa2d29a97f02204e37e9927a"
IG_ACCOUNT_ID = "26088223200849607"

# ─── Helpers ─────────────────────────────────────────────────────

def compute_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature matching Meta's format."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def send_webhook(payload: dict, label: str) -> dict:
    """Send a signed webhook POST and return results."""
    body = json.dumps(payload).encode("utf-8")
    signature = compute_signature(body, APP_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
    }

    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"{'='*60}")
    print(f"  URL: {WEBHOOK_ENDPOINT}")
    print(f"  Signature: {signature[:30]}...")
    print(f"  Payload size: {len(body)} bytes")

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(WEBHOOK_ENDPOINT, content=body, headers=headers)

        print(f"  Status: {resp.status_code}")
        print(f"  Response: {resp.text}")

        return {
            "label": label,
            "status": resp.status_code,
            "response": resp.text,
            "success": resp.status_code == 200,
        }
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"label": label, "status": 0, "response": str(e), "success": False}


# ─── Test Payloads ───────────────────────────────────────────────

def test_comment_webhook():
    """Test: Comment on a post (changes-based event)."""
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": IG_ACCOUNT_ID,
                "time": int(time.time()),
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": "17858893269000001",
                            "text": "This is a test comment from webhook test script!",
                            "from": {
                                "id": "99887766554433",
                                "username": "test_commenter"
                            },
                            "media": {
                                "id": "17890455678123456",
                                "media_product_type": "FEED"
                            }
                        }
                    }
                ]
            }
        ]
    }
    return send_webhook(payload, "Comment Webhook (changes format)")


def test_message_webhook():
    """Test: Incoming DM (messaging-based event)."""
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": IG_ACCOUNT_ID,
                "time": int(time.time()),
                "messaging": [
                    {
                        "sender": {"id": "99887766554433"},
                        "recipient": {"id": IG_ACCOUNT_ID},
                        "timestamp": int(time.time() * 1000),
                        "message": {
                            "mid": "m_test_mid_001",
                            "text": "Hello! This is a test DM from webhook test script."
                        }
                    }
                ]
            }
        ]
    }
    return send_webhook(payload, "Message/DM Webhook (messaging format)")


def test_postback_webhook():
    """Test: Button click postback (messaging-based event)."""
    import base64
    postback_payload = base64.b64encode(json.dumps({
        "automation_id": "test_auto_001",
        "action": "next_step",
        "next_step_id": "step_002",
    }).encode()).decode()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": IG_ACCOUNT_ID,
                "time": int(time.time()),
                "messaging": [
                    {
                        "sender": {"id": "99887766554433"},
                        "recipient": {"id": IG_ACCOUNT_ID},
                        "timestamp": int(time.time() * 1000),
                        "postback": {
                            "payload": postback_payload,
                            "title": "Click Me Test Button"
                        }
                    }
                ]
            }
        ]
    }
    return send_webhook(payload, "Postback Webhook (messaging format)")


def test_invalid_signature():
    """Test: Webhook with wrong signature (should be rejected)."""
    payload = {"object": "instagram", "entry": []}
    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
    }

    print(f"\n{'='*60}")
    print(f"TEST: Invalid Signature (should be 401)")
    print(f"{'='*60}")

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(WEBHOOK_ENDPOINT, content=body, headers=headers)

        print(f"  Status: {resp.status_code}")
        print(f"  Response: {resp.text}")

        return {
            "label": "Invalid Signature",
            "status": resp.status_code,
            "response": resp.text,
            "success": resp.status_code == 401,
        }
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"label": "Invalid Signature", "status": 0, "response": str(e), "success": False}


def test_non_instagram_object():
    """Test: Webhook with wrong object type (should still return 200 after saving raw)."""
    payload = {
        "object": "page",
        "entry": [{"id": "12345", "time": int(time.time())}]
    }
    return send_webhook(payload, "Non-Instagram Object (should be 400)")


# ─── Run All Tests ───────────────────────────────────────────────

if __name__ == "__main__":
    print("🔧 Instagram Webhook Live Test")
    print(f"   Target: {WEBHOOK_ENDPOINT}")
    print(f"   IG Account: {IG_ACCOUNT_ID}")

    results = []

    # Core event type tests
    results.append(test_comment_webhook())
    results.append(test_message_webhook())
    results.append(test_postback_webhook())

    # Security tests
    results.append(test_invalid_signature())

    # Edge case tests
    results.append(test_non_instagram_object())

    # ─── Summary ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    passed = 0
    failed = 0
    for r in results:
        icon = "✅" if r["success"] else "❌"
        print(f"  {icon} {r['label']} — HTTP {r['status']}")
        if r["success"]:
            passed += 1
        else:
            failed += 1

    print(f"\n  {passed}/{len(results)} passed, {failed} failed")

    if failed > 0:
        print("\n⚠️  Some tests failed. Check the backend logs:")
        print(f"     ssh into your VM and run: tail -f /path/to/backend/logs")

    print("\n📋 Next steps:")
    print("   1. Check backend logs for '→ POST /api/v1/webhooks/instagram' entries")
    print("   2. Check Cosmos DB dm_webhook_events container for raw payloads")
    print(f"      Filter by account_id = '{IG_ACCOUNT_ID}'")
