"""Lightweight Redis reachability check for cache/session configuration."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
