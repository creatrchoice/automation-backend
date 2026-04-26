"""
Manual test: send an Instagram message with a generic template + button(s).

Uses the same path as production (`InstagramAPI.send_dm`).

From repo root (with .env and Cosmos reachable):

  PYTHONPATH=. python scripts/send_ig_button_message.py \\
    --account-id instagram_17841463104040156 \\
    --recipient-id 1234567890

Comment private reply (use a real `comment_id` from a webhook; optional `--recipient-id` = commenter IGSID for logs):

  PYTHONPATH=. python scripts/send_ig_button_message.py \\
    --account-id instagram_17841463104040156 \\
    --comment-id 17995... \\
    --recipient-id 1234567890

Do not use a fake or edited `comment_id` — the API will error (often code 100 +
"The requested user cannot be found" / subcode 2534014) because the messaging
context is invalid.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Repo root on PYTHONPATH
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")


# Public placeholder image; generic cards usually need image_url
_DEFAULT_IMAGE = "https://www.facebook.com/images/fb_icon_325x325.png"


def _message_payload() -> dict:
    return {
        "type": "generic",
        "content": {
            "title": "Test card",
            "subtitle": "Button send test (scripts/send_ig_button_message.py)",
            "image_url": _DEFAULT_IMAGE,
            "buttons": [
                {
                    "type": "web_url",
                    "url": "https://www.instagram.com",
                    "title": "Open Instagram",
                }
            ],
        },
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a generic template DM via Instagram API (for debugging)."
    )
    parser.add_argument(
        "--account-id",
        required=True,
        help="Document id in dm_ig_accounts (e.g. instagram_17841463104040156)",
    )
    parser.add_argument(
        "--recipient-id",
        default=None,
        help="IG-scoped user id. Required for regular DM; optional for private reply (logging).",
    )
    parser.add_argument(
        "--comment-id",
        default=None,
        help="Real comment_id for private reply. Omit for a normal send to --recipient-id.",
    )
    args = parser.parse_args()

    if args.comment_id:
        if not args.recipient_id:
            args.recipient_id = "0"  # only used in logs; API body uses comment_id
    else:
        if not args.recipient_id:
            parser.error("Either --comment-id (private reply) or --recipient-id (DM) is required")

    from app.services.instagram_api import InstagramAPIError, instagram_api  # noqa: E402

    msg = _message_payload()
    comment_id = args.comment_id
    recipient_id = args.recipient_id

    try:
        result = await instagram_api.send_dm(
            account_id=args.account_id,
            recipient_id=recipient_id,
            message_payload=msg,
            comment_id=comment_id,
        )
        print("OK:", result)
    except ValueError as e:
        print("Account/config error:", e)
        raise SystemExit(1) from e
    except InstagramAPIError as e:
        print("InstagramAPIError:", e)
        raise SystemExit(1) from e


if __name__ == "__main__":
    asyncio.run(_main())
