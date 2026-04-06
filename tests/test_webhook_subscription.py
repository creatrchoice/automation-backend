"""
Standalone script to test webhook subscription for connected Instagram accounts.

Run on your VM where the backend is deployed:
    python tests/test_webhook_subscription.py

This will:
1. Connect to Cosmos DB
2. Find all connected Instagram accounts
3. Subscribe each account for webhook events (messages, messaging_postbacks, comments)
4. Update the account document with subscription status
"""
import asyncio
import httpx
from azure.cosmos.aio import CosmosClient
from dotenv import load_dotenv
import os

load_dotenv()

COSMOS_ENDPOINT = os.getenv("AZURE_COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("AZURE_COSMOS_KEY")
DB_NAME = os.getenv("DM_DATABASE_NAME", "dm_automation_db")
IG_ACCOUNTS_CONTAINER = os.getenv("DM_IG_ACCOUNTS_CONTAINER", "instagram_accounts")

SUBSCRIBED_FIELDS = "messages,messaging_postbacks,comments"
IG_API_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v21.0")


async def subscribe_account(ig_user_id: str, access_token: str) -> dict:
    """Subscribe an Instagram account to webhook events."""
    url = f"https://graph.instagram.com/{IG_API_VERSION}/{ig_user_id}/subscribed_apps"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={
                "subscribed_fields": SUBSCRIBED_FIELDS,
                "access_token": access_token,
            },
        )

        print(f"  POST {url}")
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")

        return {
            "status_code": response.status_code,
            "body": response.json() if response.status_code == 200 else response.text,
            "success": response.status_code == 200 and response.json().get("success", False),
        }


async def main():
    print("=" * 60)
    print("Instagram Webhook Subscription Test")
    print("=" * 60)

    if not COSMOS_ENDPOINT or not COSMOS_KEY:
        print("ERROR: AZURE_COSMOS_ENDPOINT and AZURE_COSMOS_KEY must be set")
        return

    print(f"\nConnecting to Cosmos DB: {COSMOS_ENDPOINT}")
    print(f"Database: {DB_NAME}")
    print(f"Container: {IG_ACCOUNTS_CONTAINER}")

    async with CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY) as cosmos_client:
        db = cosmos_client.get_database_client(DB_NAME)
        container = db.get_container_client(IG_ACCOUNTS_CONTAINER)

        # Find all connected Instagram accounts
        print("\nFetching connected Instagram accounts...")
        accounts = []
        async for item in container.query_items(
            query="SELECT * FROM c WHERE c.type = 'instagram_account' AND c.status = 'active'",
            enable_cross_partition_query=True,
        ):
            accounts.append(item)

        if not accounts:
            print("No active Instagram accounts found!")
            return

        print(f"Found {len(accounts)} account(s)\n")

        for account in accounts:
            ig_user_id = account.get("ig_user_id")
            username = account.get("username", "unknown")
            access_token = account.get("access_token")
            already_subscribed = account.get("webhook_subscribed", False)

            print(f"--- Account: @{username} (IG ID: {ig_user_id}) ---")
            print(f"  Already subscribed: {already_subscribed}")

            if not access_token:
                print("  SKIPPED: No access token found")
                continue

            print(f"  Subscribing to: {SUBSCRIBED_FIELDS}")
            result = await subscribe_account(ig_user_id, access_token)

            if result["success"]:
                print("  ✓ Subscription successful!")

                # Update account doc in DB
                account["webhook_subscribed"] = True
                account["webhook_fields"] = SUBSCRIBED_FIELDS.split(",")
                await container.upsert_item(body=account)
                print("  ✓ Account document updated in DB")
            else:
                print(f"  ✗ Subscription failed!")

            print()

    print("=" * 60)
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
