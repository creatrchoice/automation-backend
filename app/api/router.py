"""Main router for DM Automation API - includes all sub-routers."""
from fastapi import APIRouter

from app.api import auth, webhooks, accounts, automations, contacts, analytics, media, team

# Create main router
router = APIRouter(tags=["DM Automation"])

# Include all sub-routers
router.include_router(auth.router)
router.include_router(webhooks.router)
router.include_router(accounts.router)
router.include_router(automations.router)
router.include_router(contacts.router)
router.include_router(analytics.router)
router.include_router(media.router)
router.include_router(team.router)
