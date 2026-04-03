"""
Team / Organization management routes.

Endpoints:
  POST   /team/org                 – Create a new organization (becomes owner)
  GET    /team/org                 – Get current user's organization
  GET    /team/members             – List members of the org
  POST   /team/invite              – Invite a user by email (admin+)
  POST   /team/invite/accept       – Accept an invitation (public, token-based)
  GET    /team/invite/{token}      – Validate invite token & return info (public)
  PATCH  /team/members/{user_id}   – Update a member's role (admin+)
  DELETE /team/members/{user_id}   – Remove a member (admin+)
  DELETE /team/org                 – Delete the organization (owner only)
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, status

from app.core.config import dm_settings as settings
from app.core.errors import (
    BadRequestError,
    DuplicateEntityError,
    EntityNotFoundError,
    ForbiddenError,
    InternalServerError,
    ValidationError,
)
from app.core.permissions import (
    Role,
    require_role,
    role_from_str,
)
from app.api.deps import (
    get_current_user,
    get_cosmos_client,
    get_redis_client,
    create_access_token,
)
from app.db.cosmos_containers import (
    CONTAINER_ORGANIZATIONS,
    CONTAINER_INVITATIONS,
    CONTAINER_USERS,
)
from app.services.email_service import send_invitation_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/team", tags=["Team"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_org(cosmos_client, org_id: str) -> dict:
    """Fetch an org doc by id. Raises EntityNotFoundError if missing."""
    container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
    try:
        return await container.read_item(item=org_id, partition_key=org_id)
    except Exception:
        raise EntityNotFoundError("Organization")


async def _save_org(cosmos_client, org_doc: dict) -> dict:
    """Replace (upsert) an org document."""
    container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
    org_doc["updated_at"] = _utcnow()
    return await container.upsert_item(body=org_doc)


def _find_member(org_doc: dict, user_id: str) -> dict | None:
    for m in org_doc.get("members", []):
        if m.get("user_id") == user_id:
            return m
    return None


def _safe_org(org_doc: dict) -> dict:
    """Return org doc without sensitive internal fields."""
    return {
        "id": org_doc["id"],
        "name": org_doc.get("name"),
        "created_at": org_doc.get("created_at"),
        "updated_at": org_doc.get("updated_at"),
        "member_count": len(org_doc.get("members", [])),
    }


def _safe_member(m: dict) -> dict:
    return {
        "user_id": m["user_id"],
        "email": m.get("email"),
        "role": m.get("role"),
        "joined_at": m.get("joined_at"),
    }


# ─── Create Organization ────────────────────────────────────────────────────


@router.post("/org", status_code=status.HTTP_201_CREATED)
async def create_organization(
    name: str = Query(..., min_length=1, max_length=100, description="Organization name"),
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Create a new organization. The calling user becomes the Owner.

    After creation, a new JWT is returned that includes `org_id` so
    subsequent requests are org-scoped.
    """
    user_id = current_user.get("sub")
    email = current_user.get("email", "")

    # Check if user already has an org
    if current_user.get("org_id"):
        raise DuplicateEntityError(
            message="User already belongs to an organization",
            user_message="You already belong to an organization. Leave it first before creating a new one.",
        )

    # Check if user is already a member of any org (query orgs)
    org_container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
    query = "SELECT o.id FROM o JOIN m IN o.members WHERE m.user_id = @user_id"
    existing = []
    async for item in org_container.query_items(
        query=query,
        parameters=[{"name": "@user_id", "value": user_id}],
    ):
        existing.append(item)

    if existing:
        raise DuplicateEntityError(
            message="User already belongs to an organization",
            user_message="You are already a member of an organization.",
        )

    now = _utcnow()
    org_id = str(uuid.uuid4())

    org_doc = {
        "id": org_id,
        "name": name,
        "created_by": user_id,
        "members": [
            {
                "user_id": user_id,
                "email": email,
                "role": "owner",
                "joined_at": now,
            }
        ],
        "created_at": now,
        "updated_at": now,
    }

    try:
        await org_container.create_item(body=org_doc)
    except Exception as e:
        logger.error(f"Failed to create organization: {e}")
        raise InternalServerError(
            message=f"Create org failed: {e}",
            user_message="Could not create the organization. Please try again.",
        )

    # Issue new JWT with org_id
    new_token = create_access_token(
        data={"sub": user_id, "email": email, "org_id": org_id},
        expires_delta=timedelta(hours=24),
    )

    return {
        "message": "Organization created",
        "organization": _safe_org(org_doc),
        "access_token": new_token,
        "token_type": "bearer",
    }


# ─── Get Organization ───────────────────────────────────────────────────────


@router.get("/org")
async def get_organization(
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """Get the current user's organization details. Returns null if user has no org."""
    user_id = current_user.get("sub")
    org_id = current_user.get("org_id")

    # Look up org from DB if not in JWT
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
        return {"organization": None}

    org_doc = await _get_org(cosmos_client, org_id)
    return {
        "organization": _safe_org(org_doc),
    }


# ─── List Members ───────────────────────────────────────────────────────────


@router.get("/members")
async def list_members(
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """List all members of the organization. Returns empty list if user has no org."""
    user_id = current_user.get("sub")
    org_id = current_user.get("org_id")

    # Look up org from DB if not in JWT
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
        return {"members": []}

    org_doc = await _get_org(cosmos_client, org_id)
    return {
        "members": [_safe_member(m) for m in org_doc.get("members", [])],
    }


# ─── Invite Member ──────────────────────────────────────────────────────────


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_member(
    email: str = Query(..., description="Email to invite"),
    role: str = Query("editor", description="Role to assign: viewer, editor, admin"),
    member: dict = Depends(require_role(Role.ADMIN)),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Invite a user to the organization by email.

    Sends an invitation email with a unique link. The invite expires
    after INVITE_TOKEN_EXPIRY_HOURS (default 72h).
    """
    org_id = member["org_id"]
    inviter_email = member["email"]

    # Validate email
    if not email or "@" not in email:
        raise ValidationError(
            message="Invalid email",
            user_title="Invalid Email",
            user_message="Please enter a valid email address.",
        )

    # Validate role
    try:
        target_role = role_from_str(role)
    except ValueError:
        raise ValidationError(
            message=f"Invalid role: {role}",
            user_title="Invalid Role",
            user_message="Role must be one of: viewer, editor, admin.",
        )

    # Cannot invite as owner
    if target_role == Role.OWNER:
        raise ForbiddenError(
            message="Cannot invite as owner",
            user_message="You cannot invite someone as Owner. Transfer ownership instead.",
        )

    # Cannot invite role higher than your own
    inviter_role = member["role"]
    if target_role > inviter_role:
        raise ForbiddenError(
            message=f"Cannot invite as {role} (inviter is {member['role_name']})",
            user_message="You cannot assign a role higher than your own.",
        )

    # Check if user is already a member
    org_doc = await _get_org(cosmos_client, org_id)
    for m in org_doc.get("members", []):
        if m.get("email", "").lower() == email.lower():
            raise DuplicateEntityError(
                message=f"{email} is already a member",
                user_message=f"{email} is already a member of this organization.",
            )

    # Check for existing pending invite
    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)
    query = (
        "SELECT * FROM i WHERE i.org_id = @org_id AND i.email = @email AND i.status = 'pending'"
    )
    pending = []
    async for item in inv_container.query_items(
        query=query,
        parameters=[
            {"name": "@org_id", "value": org_id},
            {"name": "@email", "value": email.lower()},
        ],
        partition_key=org_id,
    ):
        pending.append(item)

    if pending:
        raise DuplicateEntityError(
            message=f"Pending invite already exists for {email}",
            user_message=f"An invitation has already been sent to {email}.",
        )

    # Generate invite token
    token = secrets.token_urlsafe(48)
    now = _utcnow()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_TOKEN_EXPIRY_HOURS)
    ).isoformat()

    invite_doc = {
        "id": token,
        "org_id": org_id,
        "org_name": org_doc.get("name", ""),
        "email": email.lower(),
        "role": role.lower(),
        "invited_by": inviter_email,
        "invited_by_email": inviter_email,
        "invited_at": now,
        "status": "pending",
        "created_at": now,
        "expires_at": expires_at,
    }

    try:
        await inv_container.create_item(body=invite_doc)
    except Exception as e:
        logger.error(f"Failed to create invitation: {e}")
        raise InternalServerError(
            message=f"Create invite failed: {e}",
            user_message="Could not create the invitation. Please try again.",
        )

    # Build invite link
    invite_link = f"{settings.FRONTEND_URL}/invite/accept?token={token}"

    # Send email
    try:
        await send_invitation_email(
            to_email=email,
            inviter_name=inviter_email,
            org_name=org_doc.get("name", "Your Team"),
            role=role,
            invite_link=invite_link,
        )
    except Exception as e:
        logger.error(f"Failed to send invite email: {e}")
        # Still return success — invitation was created, email can be resent
        return {
            "message": "Invitation created but email delivery failed. You can share the link manually.",
            "email": email.lower(),
            "role": role.lower(),
            "invite_link": invite_link,
            "token": token,
            "invited_at": now,
            "email_sent": False,
        }

    return {
        "message": f"Invitation sent to {email}",
        "email": email.lower(),
        "role": role.lower(),
        "invite_link": invite_link,
        "token": token,
        "invited_at": now,
        "email_sent": True,
    }


# ─── List Pending Invites ──────────────────────────────────────────────────


@router.get("/invites")
async def list_invites(
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """List all pending invitations for the user's organization."""
    user_id = current_user.get("sub")
    org_id = current_user.get("org_id")

    # Look up org from DB if not in JWT
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
        return {"invites": []}

    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)
    query = "SELECT * FROM i WHERE i.org_id = @org_id AND i.status = 'pending'"
    invites = []
    async for item in inv_container.query_items(
        query=query,
        parameters=[{"name": "@org_id", "value": org_id}],
        partition_key=org_id,
    ):
        invites.append({
            "email": item.get("email"),
            "role": item.get("role"),
            "invited_by": item.get("invited_by_email") or item.get("invited_by"),
            "invited_at": item.get("invited_at") or item.get("created_at"),
            "expires_at": item.get("expires_at"),
            "token": item.get("id"),
        })

    return {"invites": invites}


# ─── Revoke Invite ─────────────────────────────────────────────────────────


@router.delete("/invites/{token}")
async def revoke_invite(
    token: str,
    member: dict = Depends(require_role(Role.ADMIN)),
    cosmos_client=Depends(get_cosmos_client),
):
    """Revoke a pending invitation. Requires Admin or above."""
    org_id = member["org_id"]

    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)
    try:
        invite = await inv_container.read_item(item=token, partition_key=org_id)
    except Exception:
        raise EntityNotFoundError("Invitation", user_message="Invitation not found.")

    if invite.get("status") != "pending":
        raise BadRequestError(
            message="Invite is not pending",
            user_message="This invitation has already been accepted or revoked.",
        )

    invite["status"] = "revoked"
    invite["revoked_at"] = _utcnow()
    invite["revoked_by"] = member["email"]
    await inv_container.upsert_item(body=invite)

    return {"message": f"Invitation to {invite.get('email')} has been revoked"}


# ─── Validate Invite Token (public) ─────────────────────────────────────────


@router.get("/invite/{token}")
async def validate_invite(
    token: str,
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Validate an invite token and return invitation info.
    This is public — no auth required — so the invite page can show details.
    """
    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)

    # We need cross-partition query since we only have the token (id), not org_id
    query = "SELECT * FROM i WHERE i.id = @token"
    invites = []
    async for item in inv_container.query_items(
        query=query,
        parameters=[{"name": "@token", "value": token}],
    ):
        invites.append(item)

    if not invites:
        raise EntityNotFoundError(
            "Invitation",
            user_message="This invitation link is invalid or has already been used.",
        )

    invite = invites[0]

    if invite.get("status") != "pending":
        raise BadRequestError(
            message="Invite already used",
            user_message="This invitation has already been accepted or revoked.",
        )

    # Check expiry
    expires_at = invite.get("expires_at", "")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt < datetime.now(timezone.utc):
                raise BadRequestError(
                    message="Invite expired",
                    user_title="Invitation Expired",
                    user_message="This invitation has expired. Please ask your admin to send a new one.",
                )
        except (ValueError, TypeError):
            pass

    return {
        "valid": True,
        "org_name": invite.get("org_name"),
        "email": invite.get("email"),
        "role": invite.get("role"),
        "invited_by": invite.get("invited_by"),
    }


# ─── Accept Invite ──────────────────────────────────────────────────────────


@router.post("/invite/accept")
async def accept_invite(
    token: str = Query(..., description="Invitation token"),
    current_user: dict = Depends(get_current_user),
    cosmos_client=Depends(get_cosmos_client),
):
    """
    Accept an invitation. The logged-in user is added to the organization
    with the role specified in the invite.

    Returns a new JWT containing `org_id`.
    """
    user_id = current_user.get("sub")
    user_email = current_user.get("email", "")

    # Fetch the invitation
    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)
    query = "SELECT * FROM i WHERE i.id = @token"
    invites = []
    async for item in inv_container.query_items(
        query=query,
        parameters=[{"name": "@token", "value": token}],
    ):
        invites.append(item)

    if not invites:
        raise EntityNotFoundError(
            "Invitation",
            user_message="This invitation link is invalid or has already been used.",
        )

    invite = invites[0]

    if invite.get("status") != "pending":
        raise BadRequestError(
            message="Invite already used",
            user_message="This invitation has already been accepted or revoked.",
        )

    # Check expiry
    expires_at = invite.get("expires_at", "")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt < datetime.now(timezone.utc):
                raise BadRequestError(
                    message="Invite expired",
                    user_title="Invitation Expired",
                    user_message="This invitation has expired. Please ask your admin to send a new one.",
                )
        except (ValueError, TypeError):
            pass

    # Verify email matches (case-insensitive)
    if invite.get("email", "").lower() != user_email.lower():
        raise ForbiddenError(
            message=f"Email mismatch: invite for {invite.get('email')}, user is {user_email}",
            user_message=f"This invitation was sent to {invite.get('email')}. Please sign in with that email.",
        )

    org_id = invite["org_id"]
    role = invite.get("role", "viewer")

    # Check user isn't already in another org
    org_container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
    check_query = "SELECT o.id FROM o JOIN m IN o.members WHERE m.user_id = @user_id"
    existing = []
    async for item in org_container.query_items(
        query=check_query,
        parameters=[{"name": "@user_id", "value": user_id}],
    ):
        existing.append(item)

    if existing:
        raise DuplicateEntityError(
            message="User already belongs to an org",
            user_message="You already belong to an organization. Leave it first to accept this invite.",
        )

    # Add user to org
    org_doc = await _get_org(cosmos_client, org_id)
    now = _utcnow()

    org_doc["members"].append({
        "user_id": user_id,
        "email": user_email,
        "role": role,
        "joined_at": now,
    })

    await _save_org(cosmos_client, org_doc)

    # Mark invitation as accepted
    invite["status"] = "accepted"
    invite["accepted_at"] = now
    invite["accepted_by"] = user_id
    await inv_container.upsert_item(body=invite)

    # Issue new JWT with org_id
    new_token = create_access_token(
        data={"sub": user_id, "email": user_email, "org_id": org_id},
        expires_delta=timedelta(hours=24),
    )

    return {
        "message": f"You've joined {org_doc.get('name', 'the organization')} as {role}",
        "organization": _safe_org(org_doc),
        "role": role,
        "access_token": new_token,
        "token_type": "bearer",
    }


# ─── Update Member Role ─────────────────────────────────────────────────────


@router.patch("/members/{target_user_id}")
async def update_member_role(
    target_user_id: str,
    role: str = Query(..., description="New role: viewer, editor, admin"),
    member: dict = Depends(require_role(Role.ADMIN)),
    cosmos_client=Depends(get_cosmos_client),
):
    """Update a team member's role. Requires Admin or above."""
    org_id = member["org_id"]
    caller_role = member["role"]

    # Validate target role
    try:
        new_role = role_from_str(role)
    except ValueError:
        raise ValidationError(
            message=f"Invalid role: {role}",
            user_title="Invalid Role",
            user_message="Role must be one of: viewer, editor, admin.",
        )

    if new_role == Role.OWNER:
        raise ForbiddenError(
            message="Cannot assign owner via this endpoint",
            user_message="Ownership cannot be assigned through role update. Use transfer ownership instead.",
        )

    if new_role > caller_role:
        raise ForbiddenError(
            message=f"Cannot assign {role} (caller is {member['role_name']})",
            user_message="You cannot assign a role higher than your own.",
        )

    org_doc = await _get_org(cosmos_client, org_id)
    target = _find_member(org_doc, target_user_id)

    if not target:
        raise EntityNotFoundError("Member", user_message="This member was not found in the organization.")

    # Cannot change the owner's role
    if target.get("role") == "owner":
        raise ForbiddenError(
            message="Cannot change owner role",
            user_message="The owner's role cannot be changed.",
        )

    # Cannot modify someone with equal or higher role (unless you are owner)
    target_current = role_from_str(target["role"])
    if target_current >= caller_role and caller_role != Role.OWNER:
        raise ForbiddenError(
            message=f"Cannot modify role of {target['role']} (caller is {member['role_name']})",
            user_message="You cannot change the role of someone with equal or higher access.",
        )

    target["role"] = role.lower()
    await _save_org(cosmos_client, org_doc)

    return {
        "message": f"Updated {target.get('email', target_user_id)} to {role}",
        "member": _safe_member(target),
    }


# ─── Remove Member ──────────────────────────────────────────────────────────


@router.delete("/members/{target_user_id}", status_code=status.HTTP_200_OK)
async def remove_member(
    target_user_id: str,
    member: dict = Depends(require_role(Role.ADMIN)),
    cosmos_client=Depends(get_cosmos_client),
):
    """Remove a member from the organization. Requires Admin or above."""
    org_id = member["org_id"]
    caller_role = member["role"]

    org_doc = await _get_org(cosmos_client, org_id)
    target = _find_member(org_doc, target_user_id)

    if not target:
        raise EntityNotFoundError("Member", user_message="This member was not found in the organization.")

    if target.get("role") == "owner":
        raise ForbiddenError(
            message="Cannot remove owner",
            user_message="The owner cannot be removed. Transfer ownership first.",
        )

    # Can't remove someone with equal or higher role (unless owner)
    target_current = role_from_str(target["role"])
    if target_current >= caller_role and caller_role != Role.OWNER:
        raise ForbiddenError(
            message=f"Cannot remove {target['role']} (caller is {member['role_name']})",
            user_message="You cannot remove someone with equal or higher access.",
        )

    org_doc["members"] = [m for m in org_doc["members"] if m["user_id"] != target_user_id]
    await _save_org(cosmos_client, org_doc)

    return {
        "message": f"Removed {target.get('email', target_user_id)} from the organization",
    }


# ─── Delete Organization ────────────────────────────────────────────────────


@router.delete("/org", status_code=status.HTTP_200_OK)
async def delete_organization(
    member: dict = Depends(require_role(Role.OWNER)),
    cosmos_client=Depends(get_cosmos_client),
):
    """Delete the entire organization. Owner only."""
    org_id = member["org_id"]

    org_container = await cosmos_client.get_async_container_client(CONTAINER_ORGANIZATIONS)
    try:
        await org_container.delete_item(item=org_id, partition_key=org_id)
    except Exception as e:
        logger.error(f"Failed to delete org {org_id}: {e}")
        raise InternalServerError(
            message=f"Delete org failed: {e}",
            user_message="Could not delete the organization. Please try again.",
        )

    # Clean up pending invitations
    inv_container = await cosmos_client.get_async_container_client(CONTAINER_INVITATIONS)
    query = "SELECT * FROM i WHERE i.org_id = @org_id AND i.status = 'pending'"
    async for item in inv_container.query_items(
        query=query,
        parameters=[{"name": "@org_id", "value": org_id}],
        partition_key=org_id,
    ):
        try:
            await inv_container.delete_item(item=item["id"], partition_key=org_id)
        except Exception:
            pass

    return {"message": "Organization deleted"}
