"""
Manual test: send an Instagram plain-text message.

Uses the same path as production (`InstagramAPI.send_dm`), but forces text payload.

From repo root (with .env and Cosmos reachable):

  PYTHONPATH=. python3 scripts/send_ig_text_message.py \
    --account-id instagram_17841463104040156 \
    --recipient-id 1234567890 \
    --text "hello from text script"

Comment private reply (real `comment_id` from webhook; optional `--recipient-id`
= commenter IGSID for logs):

  PYTHONPATH=. python3 scripts/send_ig_text_message.py \
    --account-id instagram_17841463104040156 \
    --comment-id 17995... \
    --recipient-id 1234567890 \
    --text "thanks for your comment"

Do not use a fake/edited `comment_id` — API usually fails with code 100 and may
include "The requested user cannot be found" (often subcode 2534014).
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


def _message_payload(text: str) -> dict:
    return {
        "type": "text",
        "content": {
            "text": text,
        },
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a plain-text DM via Instagram API (for debugging)."
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
    parser.add_argument(
        "--text",
        required=True,
        help="Plain text to send.",
    )
    args = parser.parse_args()

    if args.comment_id:
        if not args.recipient_id:
            args.recipient_id = "0"  # only used in logs; API body uses comment_id
    elif not args.recipient_id:
        parser.error("Either --comment-id (private reply) or --recipient-id (DM) is required")

    from app.services.instagram_api import InstagramAPIError, instagram_api  # noqa: E402

    msg = _message_payload(args.text)

    try:
        result = await instagram_api.send_dm(
            account_id=args.account_id,
            recipient_id=args.recipient_id,
            message_payload=msg,
            comment_id=args.comment_id,
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
