#!/usr/bin/env python3
"""
Reads recent webhook events from Cosmos DB, matches them against
automations in dm_automations, builds message payloads using the
MessageBuilder pattern, and sends DM replies via Instagram API.

This mirrors the production AutomationEngine + MessageBuilder flow
but runs as a standalone local script for testing.

Usage:
    python send_from_saved_hooks.py

Env:
    WEBHOOK_FETCH_LIMIT — max recent rows from dm_webhook_events (default 50).
    Only the newest N events by received_at are loaded; raise this if your comment
    is missing because newer webhooks pushed it out of the window.
    SEND_HOOKS_FALLBACK_MESSAGE — optional; only sent if set and the saved template still cannot be coerced.
"""
import json
import os
import re
import sys
import base64
from app.workers.processor_utils import (
    canonical_trigger_type,
    match_keywords,
    normalize_keyword_rule,
)

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
COSMOS_ENDPOINT = os.getenv("AZURE_COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("AZURE_COSMOS_KEY")
DB_NAME = os.getenv("DM_DATABASE_NAME", "dm_automation_db")
# How many newest webhook rows to load (ORDER BY received_at DESC). Was hardcoded 5.
try:
    WEBHOOK_FETCH_LIMIT = max(1, int(os.getenv("WEBHOOK_FETCH_LIMIT", "50")))
except ValueError:
    WEBHOOK_FETCH_LIMIT = 50

# Only used when the step template cannot be parsed. Leave unset to skip send instead of a generic DM.
SEND_HOOKS_FALLBACK_MESSAGE = os.getenv("SEND_HOOKS_FALLBACK_MESSAGE")

INSTAGRAM_API = "https://graph.instagram.com/v21.0"


# ═══════════════════════════════════════════════════════════════════
#  MESSAGE BUILDER  (mirrors app/services/message_builder.py)
# ═══════════════════════════════════════════════════════════════════

def build_message_payload(template: dict) -> dict:
    """
    Convert automation step message template → Instagram API payload.

    Supports: text, generic (card+buttons), carousel (multi-card).
    """
    template_type = template.get("type", "text").lower()
    content = template.get("content", {})

    if template_type == "text":
        return _build_text_payload(content)
    elif template_type == "generic":
        return _build_generic_payload(content)
    elif template_type == "carousel":
        return _build_carousel_payload(content)
    else:
        print(f"  ⚠️  Unknown template type: {template_type}, falling back to text")
        return _build_text_payload(content)


def _build_text_payload(content: dict) -> dict:
    text = content.get("text", "")
    if not text:
        return {}
    return {"text": text}


def _build_generic_payload(content: dict) -> dict:
    buttons = _build_buttons(content.get("buttons", []))
    element = {"title": content.get("title", ""), "buttons": buttons}
    if content.get("subtitle"):
        element["subtitle"] = content["subtitle"]
    if content.get("image_url"):
        element["image_url"] = content["image_url"]

    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": [element],
            },
        }
    }


def _build_carousel_payload(content: dict) -> dict:
    elements = content.get("elements", [])
    if not elements:
        return {}

    carousel_elements = []
    for elem in elements:
        buttons = _build_buttons(elem.get("buttons", []))
        ce = {"title": elem.get("title", ""), "buttons": buttons}
        if elem.get("subtitle"):
            ce["subtitle"] = elem["subtitle"]
        if elem.get("image_url"):
            ce["image_url"] = elem["image_url"]
        carousel_elements.append(ce)

    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": "generic",
                "elements": carousel_elements,
            },
        }
    }


def _build_buttons(buttons: list) -> list:
    ig_buttons = []
    for btn in buttons:
        btn_type = btn.get("type", "postback").lower()
        if btn_type == "postback":
            # Encode postback payload with automation context
            payload_data = btn.get("payload", "")
            ig_buttons.append({
                "type": "postback",
                "title": btn.get("title", ""),
                "payload": payload_data,
            })
        elif btn_type == "web_url":
            ig_buttons.append({
                "type": "web_url",
                "title": btn.get("title", ""),
                "url": btn.get("url", ""),
            })
        elif btn_type == "call":
            ig_buttons.append({
                "type": "phone_number",
                "title": btn.get("title", ""),
                "payload": btn.get("phone_number", ""),
            })
    return ig_buttons


def encode_postback_payload(automation_id: str, action: str = "button_click", metadata=None) -> str:
    """Base64-encode postback payload (mirrors MessageBuilder.encode_postback_payload)."""
    data = {"automation_id": automation_id, "action": action}
    if metadata:
        data["metadata"] = metadata
    return base64.b64encode(json.dumps(data).encode()).decode()


# ═══════════════════════════════════════════════════════════════════
#  KEYWORD MATCHER (uses shared worker utility)
# ═══════════════════════════════════════════════════════════════════


def _format_keyword_for_display(k) -> str:
    nk = normalize_keyword_rule(k)
    return f'"{nk.get("value", "")}" ({nk.get("match_type", "contains")})'


def coerce_message_template(tpl) -> dict:
    """
    Normalize Cosmos/UI step shapes into {type, content} for build_message_payload.

    Handles:
    - Canonical: {"type":"text|generic|carousel","content":{...}}
    - Plain string (whole template is the DM text)
    - Flat: {"text": "..."}
    - Nested: {"content": {"text": "..."}} without type
    - Pydantic-style: message_type + text / generic_title / generic_buttons / carousel_elements
    - Aliases: body, messageText, caption, message (string)
    - Nested IG-style: {"message": {"text": "..."}}
    """
    if tpl is None:
        return {}
    if isinstance(tpl, str):
        t = tpl.strip()
        return {"type": "text", "content": {"text": t}} if t else {}
    if not isinstance(tpl, dict):
        return {}

    # Canonical
    if tpl.get("type") and isinstance(tpl.get("content"), dict):
        return tpl

    # Flat UI step (saved on step document): message_text, message_image_url, buttons
    if any(k in tpl for k in ("message_text", "message_image_url")):
        text = (tpl.get("message_text") or "").strip()
        img = (tpl.get("message_image_url") or "").strip()
        buttons = list(tpl.get("buttons") or [])
        if img or buttons:
            return {
                "type": "generic",
                "content": {
                    "title": text or " ",
                    "image_url": img or None,
                    "buttons": buttons,
                },
            }
        if text:
            return {"type": "text", "content": {"text": text}}
        return {}

    # {"message": {"text": "..."}} (Graph-style)
    msg = tpl.get("message")
    if isinstance(msg, dict) and msg.get("text"):
        return {"type": "text", "content": {"text": msg["text"]}}

    # Pydantic MessageTemplate–style
    mt = tpl.get("message_type") or tpl.get("messageType")
    if mt is not None:
        mt_s = str(mt).lower().replace(" ", "_")
        if "carousel" in mt_s:
            elems = tpl.get("carousel_elements") or tpl.get("elements") or []
            return {"type": "carousel", "content": {"elements": elems}}
        if "generic" in mt_s:
            return {
                "type": "generic",
                "content": {
                    "title": tpl.get("generic_title") or tpl.get("title") or "",
                    "subtitle": tpl.get("generic_subtitle") or tpl.get("subtitle"),
                    "image_url": tpl.get("generic_image_url") or tpl.get("image_url"),
                    "buttons": list(tpl.get("generic_buttons") or tpl.get("buttons") or []),
                },
            }
        tx = tpl.get("text") or tpl.get("body") or ""
        if isinstance(tx, str) and tx.strip():
            return {"type": "text", "content": {"text": tx}}

    # Flat text
    if "text" in tpl and tpl.get("text") is not None:
        tx = tpl.get("text")
        if isinstance(tx, str) and tx.strip():
            return {"type": "text", "content": {"text": tx}}

    # content without type
    c = tpl.get("content")
    if isinstance(c, dict):
        if c.get("text") is not None:
            return {"type": "text", "content": {"text": str(c.get("text", ""))}}
        if c.get("elements"):
            return {"type": "carousel", "content": {"elements": c.get("elements", [])}}
        if c.get("title") is not None or c.get("buttons"):
            return {"type": "generic", "content": c}

    for key in ("body", "messageText", "caption"):
        v = tpl.get(key)
        if isinstance(v, str) and v.strip():
            return {"type": "text", "content": {"text": v}}

    if isinstance(tpl.get("message"), str) and tpl["message"].strip():
        return {"type": "text", "content": {"text": tpl["message"]}}

    return {}


def _template_from_step(step: dict):
    """Pick template payload from a step (keys differ between UI/API versions)."""
    if not isinstance(step, dict):
        return None
    # UI stores copy directly on the step (no nested message object)
    if any(k in step for k in ("message_text", "message_image_url")):
        return step
    for key in ("message", "message_template", "messageTemplate", "template"):
        v = step.get(key)
        if v is None:
            continue
        if isinstance(v, dict) and len(v) == 0:
            continue
        if isinstance(v, str) and not str(v).strip():
            continue
        return v
    return None


def resolve_first_step_and_template(automation: dict):
    """
    Production uses automation['steps']; older docs use follower_branch / non_follower_branch.
    Returns (branch_label, first_step_or_none, raw_template_or_none).
    """
    for branch_key in ("non_follower_branch", "follower_branch"):
        steps = automation.get(branch_key) or []
        if steps:
            s0 = steps[0]
            tpl = _template_from_step(s0)
            return branch_key, s0, tpl
    steps = automation.get("steps") or []
    if steps:
        s0 = steps[0]
        tpl = _template_from_step(s0)
        return "steps", s0, tpl
    return None, None, None


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  WEBHOOK → AUTOMATION MATCHER → DM SENDER")
    print("  (mirrors AutomationEngine + MessageBuilder flow)")
    print("=" * 70)

    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    db = client.get_database_client(DB_NAME)

    # ─── 1. Read recent webhook events ───────────────────────
    print("\n📦 Step 1: Reading recent webhooks from dm_webhook_events...\n")
    print(f"  (newest first, limit={WEBHOOK_FETCH_LIMIT} — set WEBHOOK_FETCH_LIMIT to load more)\n")
    wh_container = db.get_container_client("dm_webhook_events")
    docs = list(wh_container.query_items(
        query="SELECT * FROM c ORDER BY c.received_at DESC OFFSET 0 LIMIT @lim",
        parameters=[{"name": "@lim", "value": WEBHOOK_FETCH_LIMIT}],
        enable_cross_partition_query=True,
    ))
    print(f"  Found {len(docs)} saved webhook(s)\n")

    if not docs:
        print("  ❌ No webhooks found. Send a DM or comment first, then retry.")
        return

    # Parse each webhook into structured events
    events = []
    for i, doc in enumerate(docs):
        parsed = _parse_webhook_doc(doc)
        events.append((doc, parsed))

        print(f"  ── Webhook #{i+1} ─────────────────────────────────")
        print(f"  ID:         {doc.get('id', '?')[:35]}")
        print(f"  Received:   {doc.get('received_at')}")
        print(f"  Type:       {parsed['type']}")
        if parsed["type"] == "message":
            print(f"  Sender:     {parsed.get('sender_id')}")
            print(f"  Text:       {parsed.get('text')}")
        elif parsed["type"] == "comment":
            print(f"  From:       @{parsed.get('from_username')} ({parsed.get('from_id')})")
            print(f"  Comment:    {parsed.get('comment_text')}")
            print(f"  Comment ID: {parsed.get('comment_id')}")
            print(f"  Media ID:   {parsed.get('media_id')}")
        elif parsed["type"] == "postback":
            print(f"  Sender:     {parsed.get('sender_id')}")
            print(f"  Button:     {parsed.get('postback_title')}")
        else:
            print(f"  (skipped — {parsed['type']})")
        print()

    # ─── 2. Get IG account access tokens ─────────────────────
    print("\n🔑 Step 2: Loading IG account access tokens...\n")
    ig_container = db.get_container_client("dm_ig_accounts")
    # SELECT * so we get `id` (internal account id); projected-only queries omit it and break matching
    accounts = list(ig_container.query_items(
        query="SELECT * FROM c",
        enable_cross_partition_query=True,
    ))
    print(f"  Found {len(accounts)} connected IG account(s)")

    token_map = {}  # ig_user_id → access_token
    account_id_map = {}  # ig_user_id → account_id (our internal ID)
    for acc in accounts:
        ig_id = acc.get("ig_user_id", "")
        token_map[ig_id] = acc.get("access_token", "")
        # Internal id is stored as `id` (e.g. instagram_<ig_user_id>); automations use that as account_id
        account_id_map[ig_id] = acc.get("account_id") or acc.get("id") or ig_id
        print(f"    @{acc.get('username')} → IG: {ig_id} → account: {account_id_map[ig_id]}")

    # ─── 3. Load automations from dm_automations ─────────────
    print(f"\n\n{'='*70}")
    print("  🤖 Step 3: Loading automations from dm_automations...")
    print(f"{'='*70}\n")

    auto_container = db.get_container_client("dm_automations")

    # Same filters as AutomationEngine.get_cached_automations; avoid IS_NULL(deleted_at) alone —
    # in Cosmos SQL, missing `deleted_at` is not the same as JSON null for IS_NULL().
    total_docs = list(auto_container.query_items(
        query="SELECT VALUE COUNT(1) FROM c",
        enable_cross_partition_query=True,
    ))
    total_n = int(total_docs[0]) if total_docs else 0
    print(f"  Total automation docs in container (unfiltered): {total_n}")

    all_automations = list(auto_container.query_items(
        query="""
            SELECT * FROM c
            WHERE c.enabled = true
            AND (NOT IS_DEFINED(c.deleted_at) OR c.deleted_at = null)
        """,
        enable_cross_partition_query=True,
    ))
    print(f"  Found {len(all_automations)} active automation(s) (enabled + not deleted)\n")

    for a in all_automations:
        trigger = a.get("trigger", {})
        keywords = trigger.get("keywords", [])
        kw_display = ", ".join(_format_keyword_for_display(k) for k in keywords) or "(catch-all)"
        print(f"  📋 {a.get('name', a.get('id', '?'))}")
        print(f"     ID:        {a.get('id')}")
        print(f"     Account:   {a.get('account_id')}")
        print(f"     Trigger:   {trigger.get('type')} → canonical={canonical_trigger_type(trigger.get('type'))!r}")
        print(f"     Keywords:  {kw_display}")
        print(f"     Post ID:   {trigger.get('post_id', '(any)')}")

        # Show branch step count (API also uses top-level `steps`)
        fb = a.get("follower_branch", [])
        nfb = a.get("non_follower_branch", [])
        st = a.get("steps") or []
        print(f"     Steps:     follower={len(fb)}, non_follower={len(nfb)}, steps={len(st)}")
        print()

    # ─── 4. Match & Send ─────────────────────────────────────
    print(f"\n{'='*70}")
    print("  📤 Step 4: MATCHING AUTOMATIONS & SENDING DMs")
    print(f"{'='*70}")

    sent_count = 0

    for i, (doc, parsed) in enumerate(events):
        event_type = parsed["type"]
        ig_account_id = parsed.get("ig_account_id", "")
        access_token = token_map.get(ig_account_id)
        account_id = account_id_map.get(ig_account_id, ig_account_id)

        if event_type not in ("message", "comment"):
            print(f"\n  ⏭️  Webhook #{i+1}: type={event_type}, skipping")
            continue

        if not access_token:
            print(f"\n  ⏭️  Webhook #{i+1}: No token for IG account {ig_account_id}, skipping")
            continue

        # Don't reply to ourselves (echo)
        if event_type == "message" and parsed.get("sender_id") == ig_account_id:
            print(f"\n  ⏭️  Webhook #{i+1}: Echo message (from self), skipping")
            continue

        # Determine trigger type and text for matching
        if event_type == "comment":
            trigger_type = "comment"
            match_text = parsed.get("comment_text", "")
            post_id = parsed.get("media_id")
        else:  # message
            trigger_type = "message"
            match_text = parsed.get("text", "")
            post_id = None

        print(f"\n  🔍 Webhook #{i+1}: Matching automations...")
        print(f"     Trigger:  {trigger_type}")
        print(f"     Text:     \"{match_text[:80]}\"")
        print(f"     Account:  {account_id}")
        if post_id:
            print(f"     Post ID:  {post_id}")

        # Find matching automations (same logic as AutomationEngine.match_automations)
        matched_automations = []
        for automation in all_automations:
            # Filter by account
            if automation.get("account_id") != account_id:
                continue

            trigger = automation.get("trigger", {})

            # Filter by trigger type (DB may use COMMENT / message_received / etc.)
            if canonical_trigger_type(trigger.get("type")) != trigger_type:
                continue

            # Filter by post_id (if automation is post-specific)
            if post_id and trigger.get("post_id"):
                if trigger["post_id"] != post_id:
                    continue

            # Match keywords
            keywords = trigger.get("keywords", [])
            if match_keywords(match_text, keywords):
                matched_automations.append(automation)

        if not matched_automations:
            print(f"     ❌ No matching automations found")
            continue

        print(f"     ✅ Matched {len(matched_automations)} automation(s) — sending for each")

        # Build recipient once per webhook (same for all automations on this event)
        if event_type == "comment":
            comment_id = parsed.get("comment_id")
            if not comment_id:
                print(f"     ❌ No comment_id, can't send comment-to-DM")
                continue
            recipient = {"comment_id": comment_id}
            print(f"     Recipient: comment_id={comment_id}")
        else:
            sender_id = parsed.get("sender_id")
            if not sender_id:
                print(f"     ❌ No sender_id, can't reply")
                continue
            recipient = {"id": sender_id}
            print(f"     Recipient: id={sender_id}")

        url = f"{INSTAGRAM_API}/{ig_account_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        for automation in matched_automations:
            automation_id = automation.get("id")
            automation_name = automation.get("name", automation_id)

            print(f"\n  ⚡ Executing automation: {automation_name}")
            print(f"     Automation ID: {automation_id}")

            branch_name, first_step, raw_template = resolve_first_step_and_template(automation)
            if not first_step:
                print(f"     ⚠️  No steps on branches or steps[]")

            step_id = first_step.get("id", "?") if first_step else "—"
            coerced = coerce_message_template(raw_template or {})

            print(f"     Branch:   {branch_name or '(none)'}")
            print(f"     Step:     {step_id}")
            if raw_template is not None:
                print(f"     Raw (DB): {json.dumps(raw_template, default=str)[:400]}")
            print(f"     Coerced:  {json.dumps(coerced)[:400]}")

            message_payload = build_message_payload(coerced)
            if not message_payload and SEND_HOOKS_FALLBACK_MESSAGE:
                fb = {"type": "text", "content": {"text": SEND_HOOKS_FALLBACK_MESSAGE}}
                print(f"     Using SEND_HOOKS_FALLBACK_MESSAGE (template still empty after coerce)")
                message_payload = build_message_payload(fb)

            if not message_payload:
                print(f"     ❌ Could not build message from saved template (no fallback set).")
                if first_step:
                    print(f"     Step keys: {list(first_step.keys())}")
                continue

            print(f"     Built payload: {json.dumps(message_payload)[:200]}")

            request_body = {"recipient": recipient, "message": message_payload}

            print(f"\n     📤 Sending DM...")
            print(f"     URL:     {url}")
            print(f"     Body:    {json.dumps(request_body)[:300]}")

            try:
                resp = httpx.post(url, json=request_body, headers=headers, timeout=15)
                print(f"     Status:  {resp.status_code}")
                print(f"     Response: {resp.text}")
                if resp.status_code == 200:
                    sent_count += 1
                    resp_data = resp.json()
                    print(f"     ✅ Message ID: {resp_data.get('message_id', '?')}")
                else:
                    print(f"     ❌ Failed — check response above")
            except Exception as e:
                print(f"     ❌ Error: {e}")

    # ─── Summary ─────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  DONE — {sent_count} DM(s) sent via automation message templates")
    print(f"{'='*70}")


# ═══════════════════════════════════════════════════════════════════
#  WEBHOOK PARSER
# ═══════════════════════════════════════════════════════════════════

def _parse_webhook_doc(doc: dict) -> dict:
    """Parse a saved webhook document into structured event data."""
    raw = doc.get("raw_payload") or {}
    if not raw and doc.get("raw_body"):
        try:
            raw = json.loads(doc["raw_body"])
        except Exception:
            return {"type": "unparseable"}

    entries = raw.get("entry", [])
    if not entries:
        return {"type": "empty"}

    entry = entries[0]
    ig_account_id = entry.get("id", "unknown")

    # DM / Postback
    messaging = entry.get("messaging", [])
    if messaging:
        msg = messaging[0]
        sender_id = msg.get("sender", {}).get("id")
        recipient_id = msg.get("recipient", {}).get("id")

        if "postback" in msg:
            return {
                "type": "postback",
                "ig_account_id": ig_account_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "postback_title": msg.get("postback", {}).get("title"),
                "postback_payload": msg.get("postback", {}).get("payload"),
            }
        else:
            return {
                "type": "message",
                "ig_account_id": ig_account_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "text": msg.get("message", {}).get("text", ""),
                "mid": msg.get("message", {}).get("mid"),
            }

    # Comment
    changes = entry.get("changes", [])
    if changes:
        change = changes[0]
        if change.get("field") == "comments":
            val = change.get("value", {})
            return {
                "type": "comment",
                "ig_account_id": ig_account_id,
                "comment_id": val.get("id"),
                "comment_text": val.get("text", ""),
                "from_id": val.get("from", {}).get("id"),
                "from_username": val.get("from", {}).get("username"),
                "media_id": val.get("media", {}).get("id"),
            }

    return {"type": "unknown"}


if __name__ == "__main__":
    main()
