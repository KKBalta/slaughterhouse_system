"""Lightweight Redis reachability check and shared Redis primitives."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Lua script: atomically INCR a counter and set TTL on first call only.
# Prevents the race where two concurrent workers both read count=0 and both
# reset the window.  Returns the new count.
_LUA_RATE_INCR = (
    "local n = redis.call('INCR', KEYS[1]); if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; return n"
)


def atomic_rate_incr(key: str, window: int) -> int:
    """Atomically increment a rate-limit counter; return the new count.

    On Redis, uses a single Lua script so INCR + EXPIRE are one atomic op and
    the raw key bypasses Django's KEY_FUNCTION (rate limits are global there).

    When the default cache is NOT Redis (e.g. USE_REDIS=False → DatabaseCache),
    falls back to the Django cache framework with a FIXED window keyed by the
    wall-clock bucket ``floor(now / window)``. We can't use cache.incr() to keep
    a single key alive for exactly ``window`` seconds: DatabaseCache inherits
    BaseCache.incr(), whose internal set() drops the timeout back to the cache
    default (300s), so any sub-300s request stream would keep the counter alive
    forever. The same is true of any "reset the TTL on every write" scheme — it
    turns the fixed window into a sliding one that never expires under steady
    polling, which would permanently 429 the high-rate edge endpoints
    (sessions ~1/5s, heartbeat ~1/30s, print-jobs up to 60/60s). Bucketing makes
    the counter vanish when the bucket rolls over, independent of per-entry TTL,
    reproducing the Redis INCR+EXPIRE-on-first fixed-window semantics.

    The bucket count is namespaced by the active schema via the cache
    KEY_FUNCTION rather than being strictly global, and the read-modify-write is
    near-atomic (a small under-count under concurrency is fine for rate limiting).

    Falls back to 0 (fail-open) on any error — rate limiting must never block
    requests because of infra issues.

    Args:
        key: Rate-limit counter key.
        window: Fixed window length in seconds.
    """
    try:
        from django.conf import settings

        if settings.CACHES["default"]["BACKEND"] == "django_redis.cache.RedisCache":
            from django_redis import get_redis_connection

            conn = get_redis_connection("default")
            return int(conn.eval(_LUA_RATE_INCR, 1, key, window))

        # Non-Redis backend (DatabaseCache / LocMem). Fixed window via a
        # wall-clock bucket key; TTL is pinned to ``window`` so stale buckets
        # expire promptly instead of lingering on the cache default.
        from django.core.cache import cache

        bucket_key = f"{key}:{int(time.time() // window)}"
        # Atomic insert-if-absent: only one concurrent first-hit seeds the bucket.
        if cache.add(bucket_key, 1, timeout=window):
            return 1
        current = cache.get(bucket_key)
        if current is None:
            cache.add(bucket_key, 1, timeout=window)
            return 1
        new_value = int(current) + 1
        cache.set(bucket_key, new_value, timeout=window)
        return new_value
    except Exception as exc:
        logger.warning("atomic_rate_incr failed for key %r (rate limiting bypassed): %s", key, exc)
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
