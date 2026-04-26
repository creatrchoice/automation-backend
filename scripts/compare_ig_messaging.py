"""
A/B: send the same text DM, then a generic template with a button, using identical
recipient/comment context. Uses production `InstagramAPI.send_dm` twice.

  PYTHONPATH=. python3 scripts/compare_ig_messaging.py \
    --account-id instagram_... \
    --recipient-id 123... \
    --text "Text probe"
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

_DEFAULT_IMAGE = "https://www.facebook.com/images/fb_icon_325x325.png"


def _text_payload(t: str) -> dict:
    return {"type": "text", "content": {"text": t}}


def _generic_payload() -> dict:
    return {
        "type": "generic",
        "content": {
            "title": "Template probe",
            "subtitle": "After text send (compare_ig_messaging.py)",
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
        description="Send text DM, then generic+button; print both outcomes."
    )
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--recipient-id", default=None)
    parser.add_argument("--comment-id", default=None)
    parser.add_argument(
        "--text",
        default="Text probe (compare_ig_messaging.py)",
        help="First message body (plain text).",
    )
    args = parser.parse_args()

    if args.comment_id and not args.recipient_id:
        args.recipient_id = "0"
    elif not args.comment_id and not args.recipient_id:
        parser.error("Need --comment-id and/or --recipient-id")

    from app.services.instagram_api import InstagramAPIError, instagram_api  # noqa: E402

    base_kw = {
        "account_id": args.account_id,
        "recipient_id": args.recipient_id,
        "comment_id": args.comment_id,
    }

    print("--- 1) text ---")
    try:
        r1 = await instagram_api.send_dm(
            **base_kw,
            message_payload=_text_payload(args.text),
        )
        print("OK:", r1)
    except ValueError as e:
        print("Account/config error:", e)
        raise SystemExit(1) from e
    except InstagramAPIError as e:
        print("FAIL:", e)

    print("--- 2) generic+button ---")
    try:
        r2 = await instagram_api.send_dm(
            **base_kw,
            message_payload=_generic_payload(),
        )
        print("OK:", r2)
    except InstagramAPIError as e:
        print("FAIL:", e)


if __name__ == "__main__":
    asyncio.run(_main())
