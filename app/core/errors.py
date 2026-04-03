"""
Centralized error management for DM Automation API.

All API errors extend AppError and carry:
  - status_code: HTTP status code
  - message: Internal/developer-facing message (logged, not shown to user)
  - user_title: Short user-facing title (e.g. "Invalid Credentials")
  - user_message: User-facing explanation (defaults to message if not set)

The global exception handler in main.py catches AppError subclasses and
returns a consistent JSON response shape:
{
    "error": {
        "code": "ENTITY_NOT_FOUND",
        "title": "Not Found",
        "message": "The requested account was not found.",
    }
}
"""

from typing import Optional


class AppError(Exception):
    """Base application error. All custom errors extend this."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    default_user_title: str = "Error"
    default_user_message: Optional[str] = None  # None = fallback to message

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        *,
        user_title: Optional[str] = None,
        user_message: Optional[str] = None,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.user_title = user_title or self.default_user_title
        self.user_message = user_message or self.default_user_message or message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


# ── 400 Bad Request ──────────────────────────────────────────────────────────


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"
    default_user_title = "Invalid Request"


class ValidationError(AppError):
    status_code = 400
    code = "VALIDATION_ERROR"
    default_user_title = "Validation Error"


class DuplicateEntityError(AppError):
    status_code = 409
    code = "DUPLICATE_ENTITY"
    default_user_title = "Already Exists"


# ── 401 Unauthorized ─────────────────────────────────────────────────────────


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    default_user_title = "Unauthorized"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "INVALID_CREDENTIALS"
    default_user_title = "Invalid Credentials"
    default_user_message = "The email or password you entered is incorrect."


class TokenExpiredError(AppError):
    status_code = 401
    code = "TOKEN_EXPIRED"
    default_user_title = "Session Expired"
    default_user_message = "Your session has expired. Please sign in again."


class InvalidTokenError(AppError):
    status_code = 401
    code = "INVALID_TOKEN"
    default_user_title = "Invalid Session"
    default_user_message = "Your session is invalid. Please sign in again."


# ── 403 Forbidden ────────────────────────────────────────────────────────────


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    default_user_title = "Access Denied"
    default_user_message = "You don't have permission to perform this action."


# ── 404 Not Found ────────────────────────────────────────────────────────────


class EntityNotFoundError(AppError):
    status_code = 404
    code = "ENTITY_NOT_FOUND"
    default_user_title = "Not Found"

    def __init__(self, entity: str = "Resource", **kwargs):
        if "message" not in kwargs:
            kwargs.setdefault("message", f"{entity} not found")
        if "user_message" not in kwargs:
            kwargs["user_message"] = f"The requested {entity.lower()} could not be found."
        super().__init__(**kwargs)


# ── 429 Rate Limited ─────────────────────────────────────────────────────────


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    default_user_title = "Too Many Requests"
    default_user_message = "You're making requests too quickly. Please wait a moment and try again."


# ── 500 Internal Server Error ────────────────────────────────────────────────


class InternalServerError(AppError):
    status_code = 500
    code = "INTERNAL_ERROR"
    default_user_title = "Something Went Wrong"
    default_user_message = "An unexpected error occurred. Please try again later."


# ── 502 / 503 External Service Errors ────────────────────────────────────────


class ExternalServiceError(AppError):
    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service: str = "External service", **kwargs):
        if "message" not in kwargs:
            kwargs.setdefault("message", f"{service} is unavailable")
        kwargs.setdefault("user_title", "Service Unavailable")
        kwargs.setdefault("user_message", f"We're having trouble connecting to {service}. Please try again later.")
        super().__init__(**kwargs)


class DatabaseError(AppError):
    status_code = 503
    code = "DATABASE_ERROR"
    default_user_title = "Service Unavailable"
    default_user_message = "We're experiencing a temporary issue. Please try again in a moment."
