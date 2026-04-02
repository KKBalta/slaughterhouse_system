"""Lightweight Redis reachability check and shared Redis primitives."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lua script: atomically INCR a counter and set TTL on first call only.
# Prevents the race where two concurrent workers both read count=0 and both
# reset the window.  Returns the new count.
_LUA_RATE_INCR = (
    "local n = redis.call('INCR', KEYS[1]); "
    "if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; "
    "return n"
)


def atomic_rate_incr(key: str, window: int) -> int:
    """Atomically increment a rate-limit counter; return the new count.

    Uses a single Redis Lua script so INCR + EXPIRE are one atomic operation.
    Falls back to 0 (fail-open) when Redis is unreachable — rate limiting
    should never block requests because of infra issues.

    Args:
        key: Raw Redis key (bypasses Django's KEY_FUNCTION intentionally;
             rate limits are global, not per-tenant).
        window: TTL in seconds for the sliding window.
    """
    try:
        from django_redis import get_redis_connection

        conn = get_redis_connection("default")
        return int(conn.eval(_LUA_RATE_INCR, 1, key, window))
    except Exception as exc:
        logger.debug("atomic_rate_incr failed for key %r: %s", key, exc)
        return 0


def is_redis_reachable(url: str, *, timeout_s: float = 0.35) -> bool:
    """
    Return True if a PING against ``url`` succeeds within ``timeout_s``.

    Used at settings load time only; runtime Redis outages are not handled here.
    """
    try:
        import redis
    except ImportError:
        logger.warning("redis package not available; cache will not use Redis")
        return False
    try:
        client = redis.from_url(url, socket_connect_timeout=timeout_s, socket_timeout=timeout_s)
        return bool(client.ping())
    except Exception as exc:
        logger.debug("Redis ping failed (%s): %s", url, exc)
        return False
