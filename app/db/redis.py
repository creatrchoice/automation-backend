"""Redis client wrapper for DM Automation."""
import logging
import ssl as ssl_module
import redis
from app.core.config import dm_settings

logger = logging.getLogger(__name__)


def _build_redis_kwargs() -> dict:
    """Build Redis connection kwargs from settings."""
    kwargs = {
        "host": dm_settings.REDIS_HOST,
        "port": dm_settings.REDIS_PORT,
        "db": dm_settings.REDIS_DB,
        "decode_responses": True,
    }

    if dm_settings.REDIS_USERNAME:
        kwargs["username"] = dm_settings.REDIS_USERNAME
    if dm_settings.REDIS_PASSWORD:
        kwargs["password"] = dm_settings.REDIS_PASSWORD

    if dm_settings.REDIS_SSL:
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = ssl_module.CERT_NONE

    return kwargs


def create_redis_client() -> redis.Redis:
    """Create a synchronous Redis client."""
    try:
        kwargs = _build_redis_kwargs()
        client = redis.Redis(**kwargs)
        # Test connection
        client.ping()
        logger.info(f"Redis connected to {dm_settings.REDIS_HOST}:{dm_settings.REDIS_PORT}")
        return client
    except redis.ConnectionError as e:
        logger.warning(f"Redis connection failed (will retry on use): {e}")
        return redis.Redis(**_build_redis_kwargs())
    except Exception as e:
        logger.error(f"Redis client creation failed: {e}")
        raise


# Global sync Redis client (used by Celery workers and sync services)
try:
    redis_client = create_redis_client()
except Exception:
    logger.warning("Redis client initialization deferred - will connect on first use")
    redis_client = redis.Redis(**_build_redis_kwargs())
