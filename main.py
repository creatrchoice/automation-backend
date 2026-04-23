"""
Instagram DM Automation Platform - FastAPI Backend
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import dm_settings
from app.core.errors import AppError
from app.api.router import router as dm_router
from app.db.cosmos_containers import initialize_containers

logger = logging.getLogger(__name__)

# Configure root logger for visibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Suppress verbose Azure HTTP request/response header logs.
logging.getLogger("azure.cosmos._cosmos_http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)


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


# ── Request Logging Middleware ────────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every incoming request and outgoing response with timing."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        client_ip = request.client.host if request.client else "unknown"

        # Log request
        logger.info(
            f"→ {method} {path}{'?' + query if query else ''} "
            f"[client={client_ip}]"
        )

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = round((time.time() - start) * 1000)
            logger.error(
                f"✗ {method} {path} — UNHANDLED EXCEPTION in {duration_ms}ms: {e}"
            )
            raise

        duration_ms = round((time.time() - start) * 1000)

        # Log response
        status_code = response.status_code
        level = logging.WARNING if status_code >= 400 else logging.INFO
        logger.log(
            level,
            f"← {method} {path} — {status_code} in {duration_ms}ms"
        )

        return response


# CORS (must be added before custom middleware so CORS headers are always set)
app.add_middleware(
    CORSMiddleware,
    allow_origins=dm_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging
app.add_middleware(RequestLoggingMiddleware)


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
