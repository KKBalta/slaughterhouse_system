"""Redis/Django-cache snapshots for Edge print-worker activity (fast dashboard reads)."""

from __future__ import annotations

import json
import logging

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

_EDGE_PW_TTL = 600  # seconds; refreshed on every poll / ack
_KEY = "edge_pw:{edge_id}"


def record_edge_print_poll(edge_id, *, site_id, pending_jobs_in_response: int) -> None:
    """Record last successful print-jobs poll for an Edge (worker)."""
    try:
        payload = {
            "last_poll_at": timezone.now().isoformat(),
            "site_id": str(site_id),
            "pending_jobs_in_response": pending_jobs_in_response,
        }
        cache.set(_KEY.format(edge_id=edge_id), json.dumps(payload), _EDGE_PW_TTL)
    except Exception:
        logger.exception("record_edge_print_poll failed for edge %s", edge_id)


def record_edge_print_ack(edge_id, *, job_id, ack_status: str) -> None:
    """Merge last ACK into the same worker key (extends TTL)."""
    try:
        key = _KEY.format(edge_id=edge_id)
        raw = cache.get(key)
        base: dict = json.loads(raw) if raw else {}
        base["last_ack_at"] = timezone.now().isoformat()
        base["last_ack_job_id"] = str(job_id)
        base["last_ack_status"] = ack_status
        cache.set(key, json.dumps(base), _EDGE_PW_TTL)
    except Exception:
        logger.exception("record_edge_print_ack failed for edge %s", edge_id)


def get_edge_print_worker_pulse(edge_id):
    """Return decoded pulse dict or None if no recent activity in cache."""
    raw = cache.get(_KEY.format(edge_id=edge_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
