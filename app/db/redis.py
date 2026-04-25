"""Redis client wrapper for DM Automation."""
import logging
import ssl as ssl_module
import redis
from app.core.config import dm_settings

logger = logging.getLogger(__name__)


def redis_should_use_tls() -> bool:
    """
    Use TLS (rediss) when REDIS_SSL is set, or for known managed-Redis hostnames.

    Redis Cloud / Redis Enterprise Cloud public endpoints require TLS; using plain
    redis:// against a TLS port causes: [SSL] record layer failure.
    """
    if dm_settings.REDIS_SSL:
        return True
    h = (dm_settings.REDIS_HOST or "").lower()
    return any(
        x in h
        for x in (
            "redislabs.com",
            "redis.cloud",
            "redis-cloud.com",
            "redisenterprise.com",
        )
    )


def build_redis_ssl_context():
    """SSL context for Redis Cloud (managed certs; disable verify for simplicity)."""
    ctx = ssl_module.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl_module.CERT_NONE
    return ctx


def _build_redis_kwargs(use_tls: bool = False) -> dict:
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

    if use_tls:
        kwargs["ssl"] = build_redis_ssl_context()

    return kwargs


def create_redis_client() -> redis.Redis:
    """Create a synchronous Redis client."""
    prefer_tls = redis_should_use_tls()
    attempts = [prefer_tls] if prefer_tls else [False]
    if prefer_tls:
        # Some providers expose plaintext endpoints even when REDIS_SSL=true.
        # Fall back to non-TLS automatically on SSL handshake failures.
        attempts.append(False)

    last_error = None
    for use_tls in attempts:
        try:
            kwargs = _build_redis_kwargs(use_tls=use_tls)
            client = redis.Redis(**kwargs)
            client.ping()
            mode = "TLS" if use_tls else "plaintext"
            logger.info(
                "Redis connected (%s) to %s:%s",
                mode,
                dm_settings.REDIS_HOST,
                dm_settings.REDIS_PORT,
            )
            return client
        except Exception as e:
            last_error = e
            mode = "TLS" if use_tls else "plaintext"
            logger.warning("Redis %s connection failed: %s", mode, e)

    logger.warning("Redis connection failed (will retry on use): %s", last_error)
    return redis.Redis(**_build_redis_kwargs(use_tls=False))


# Global sync Redis client (used by Celery workers and sync services)
try:
    redis_client = create_redis_client()
except Exception:
    logger.warning("Redis client initialization deferred - will connect on first use")
    redis_client = redis.Redis(**_build_redis_kwargs(use_tls=False))
