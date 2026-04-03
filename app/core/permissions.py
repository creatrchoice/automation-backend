"""
Centralized role-based permission system.

Roles (highest → lowest):
  owner  – Full access. Can manage billing and delete the workspace.
  admin  – Can manage team members, accounts, and all automations.
  editor – Can create and edit automations. Cannot manage team.
  viewer – Read-only access. Can view automations and analytics.

Usage in route handlers:

    from app.core.permissions import require_role, Role

    @router.post("/automations")
    async def create_automation(
        member = Depends(require_role(Role.EDITOR)),
        ...
    ):
        org_id = member["org_id"]
        ...

`require_role(min_role)` returns a FastAPI dependency that:
  1. Extracts the JWT (via get_current_user)
  2. Looks up the user's membership doc in dm_organizations
  3. Verifies role >= min_role
  4. Returns the membership context dict
"""

from enum import IntEnum
from typing import Optional
from fastapi import Depends

from app.core.errors import ForbiddenError, EntityNotFoundError
from app.api.deps import get_current_user, get_cosmos_client
from app.db.cosmos_containers import CONTAINER_ORGANIZATIONS


class Role(IntEnum):
    """Roles ordered by privilege level (higher = more powerful)."""
    VIEWER = 10
    EDITOR = 20
    ADMIN = 30
    OWNER = 40


# String ↔ enum helpers
ROLE_MAP = {r.name.lower(): r for r in Role}


def role_from_str(s: str) -> Role:
    """Convert a lowercase role name to Role enum. Raises ValueError if invalid."""
    r = ROLE_MAP.get(s.lower())
    if r is None:
        raise ValueError(f"Unknown role: {s}. Valid roles: {list(ROLE_MAP.keys())}")
    return r


def require_role(min_role: Role):
    """
    FastAPI dependency factory.

    Returns a dependency that resolves to a dict:
        {
            "org_id": str,
            "user_id": str,
            "email": str,
            "role": Role,
            "role_name": str,   # e.g. "admin"
        }

    Raises ForbiddenError if the user's role is below `min_role`.
    """

    async def _check(
        current_user: dict = Depends(get_current_user),
        cosmos_client=Depends(get_cosmos_client),
    ) -> dict:
        user_id = current_user.get("sub")
        email = current_user.get("email", "")
        org_id = current_user.get("org_id")

        # Fallback: look up org from DB if not in JWT
        if not org_id:
            try:
                container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
                query = "SELECT o.id FROM o JOIN m IN o.members WHERE m.user_id = @uid"
                async for item in container.query_items(
                    query=query,
                    parameters=[{"name": "@uid", "value": user_id}],
                ):
                    org_id = item.get("id")
                    break
            except Exception:
                pass

        if not org_id:
            raise ForbiddenError(
                message="User has no organization",
                user_message="You need to be part of an organization to perform this action.",
            )

        # Fetch organization document
        container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
        try:
            org_doc = await container.read_item(item=org_id, partition_key=org_id)
        except Exception:
            raise EntityNotFoundError("Organization")

        # Find user's membership
        members = org_doc.get("members", [])
        member_entry = None
        for m in members:
            if m.get("user_id") == user_id:
                member_entry = m
                break

        if member_entry is None:
            raise ForbiddenError(
                message=f"User {user_id} is not a member of org {org_id}",
                user_message="You are not a member of this organization.",
            )

        try:
            user_role = role_from_str(member_entry["role"])
        except ValueError:
            raise ForbiddenError(
                message=f"Unknown role '{member_entry['role']}' for user {user_id}",
                user_message="Your account has an invalid role. Contact your admin.",
            )

        if user_role < min_role:
            raise ForbiddenError(
                message=f"Role {user_role.name} < required {min_role.name}",
                user_message=f"This action requires at least {min_role.name.capitalize()} access.",
            )

        return {
            "org_id": org_id,
            "user_id": user_id,
            "email": email,
            "role": user_role,
            "role_name": user_role.name.lower(),
        }

    return _check


# Convenience pre-built dependencies
require_viewer = require_role(Role.VIEWER)
require_editor = require_role(Role.EDITOR)
require_admin = require_role(Role.ADMIN)
require_owner = require_role(Role.OWNER)
