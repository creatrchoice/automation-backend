"""
Instagram DM Automation Platform - FastAPI Backend
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import dm_settings
from app.core.errors import AppError
from app.api.router import router as dm_router
from app.db.cosmos_containers import initialize_containers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    try:
        await initialize_containers()
        print("Cosmos DB containers initialized")
    except Exception as e:
        print(f"Warning: Cosmos DB init failed (will retry on first request): {e}")
    yield
    # Shutdown (cleanup if needed)


app = FastAPI(
    title="Instagram DM Automation API",
    description="Automate Instagram DMs triggered by comments, story reactions, and incoming messages.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Global Error Handler ─────────────────────────────────────────────────────

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """
    Catch all AppError subclasses and return a consistent JSON response.

    Response shape:
    {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "title": "Invalid Credentials",
            "message": "The email or password you entered is incorrect."
        }
    }
    """
    logger.error(f"[{exc.code}] {exc.message} (path={request.url.path})")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "title": exc.user_title,
                "message": exc.user_message,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """
    Catch-all for any unhandled exceptions.
    Returns a generic error so internals are never leaked.
    """
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "title": "Something Went Wrong",
                "message": "An unexpected error occurred. Please try again later.",
            }
        },
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=dm_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include DM Automation routes at /api/v1
app.include_router(dm_router, prefix="/api/v1")

# Also mount auth and webhooks at root level for Meta-registered callback URLs.
# Meta requires exact URL match for:
#   - OAuth callback: /auth/instagram/callback
#   - Webhook endpoint: /webhooks/instagram
from app.api import auth as auth_module, webhooks as webhooks_module
app.include_router(auth_module.router, tags=["Auth (Root)"])
app.include_router(webhooks_module.router, tags=["Webhooks (Root)"])


@app.get("/")
async def root():
    return {
        "service": "Instagram DM Automation API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
