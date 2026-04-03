"""Dependency injection for DM Automation API."""
import logging
from typing import Optional
from datetime import datetime, timedelta

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials as HTTPAuthCredentials
import jwt
import redis.asyncio as aioredis
from app.core.config import dm_settings as settings
from app.core.errors import UnauthorizedError, TokenExpiredError, InvalidTokenError
from app.db.cosmos_db import CosmosDBClient

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Global instances
_cosmos_client: Optional[CosmosDBClient] = None
_redis_client: Optional[aioredis.Redis] = None


async def get_cosmos_client() -> CosmosDBClient:
    """Get or create Cosmos DB client (async)."""
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosDBClient()
        await _cosmos_client.connect_async()
    return _cosmos_client


async def get_redis_client() -> aioredis.Redis:
    """Get or create Redis client (async)."""
    global _redis_client
    if _redis_client is None:
        import ssl as ssl_module
        scheme = "rediss" if settings.REDIS_SSL else "redis"
        kwargs = {
            "username": settings.REDIS_USERNAME if settings.REDIS_USERNAME else None,
            "password": settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
            "decode_responses": True,
        }
        if settings.REDIS_SSL:
            kwargs["ssl_cert_reqs"] = ssl_module.CERT_NONE
        _redis_client = aioredis.from_url(
            f"{scheme}://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            **kwargs,
        )
    return _redis_client


async def get_current_user(
    credentials: Optional[HTTPAuthCredentials] = Depends(security),
) -> dict:
    """Extract and validate JWT token from Authorization header."""
    if not credentials:
        raise UnauthorizedError(message="Missing authorization token")

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )

        user_id: str = payload.get("sub")
        if not user_id:
            raise InvalidTokenError(message="Token missing user_id claim")

        exp = payload.get("exp")
        if exp:
            if datetime.utcfromtimestamp(exp) < datetime.utcnow():
                raise TokenExpiredError()

        return payload

    except TokenExpiredError:
        raise
    except InvalidTokenError:
        raise
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise InvalidTokenError(message=f"Invalid token: {e}")
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise InvalidTokenError(message=f"Token validation failed: {e}")


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return encoded_jwt
