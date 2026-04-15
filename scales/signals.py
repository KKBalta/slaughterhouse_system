"""Sync EdgeSetupCodeIndex in public schema when tenant EdgeSetupCode changes."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_tenants.utils import get_public_schema_name, schema_context

logger = logging.getLogger(__name__)


def sync_setup_code_to_public_index(setup_code) -> None:
    """
    Upsert or mark-consumed the public-schema EdgeSetupCodeIndex row
    for the given tenant-schema EdgeSetupCode instance.

    Must be called from within the tenant schema context (the normal case
    inside post_save of a tenant model).
    """
    if not getattr(settings, "USE_MULTITENANT", False):
        return

    from django.db import connection

    tenant = getattr(connection, "tenant", None)
    if tenant is None or tenant.schema_name == get_public_schema_name():
        return

    from tenants.models import Client, EdgeSetupCodeIndex

    with schema_context(get_public_schema_name()):
        try:
            client = Client.objects.get(schema_name=tenant.schema_name)
        except Client.DoesNotExist:
            logger.warning("sync_setup_code_to_public_index: tenant %s not found", tenant.schema_name)
            return

        is_consumed = setup_code.used_at is not None or not setup_code.is_active

        EdgeSetupCodeIndex.objects.update_or_create(
            code=setup_code.code,
            defaults={
                "tenant": client,
                "tenant_schema": tenant.schema_name,
                "setup_code_id": setup_code.pk,
                "expires_at": setup_code.expires_at,
                "is_consumed": is_consumed,
            },
        )


def remove_setup_code_from_public_index(code: str) -> None:
    """Remove the public-schema index row for a revoked/deleted setup code."""
    if not getattr(settings, "USE_MULTITENANT", False):
        return

    from tenants.models import EdgeSetupCodeIndex

    with schema_context(get_public_schema_name()):
        EdgeSetupCodeIndex.objects.filter(code=code).delete()


@receiver(post_save, sender="scales.EdgeSetupCode")
def sync_edge_setup_code_index(sender, instance, **kwargs):
    """Keep public-schema lookup table in sync on every EdgeSetupCode save."""
    try:
        sync_setup_code_to_public_index(instance)
    except Exception:
        logger.exception("Failed to sync EdgeSetupCode %s to public index", instance.code)


@receiver(post_save, sender="scales.EdgeDevice")
def sync_edge_device_index_on_save(sender, instance, **kwargs):
    """Keep public EdgeDeviceIndex in sync when EdgeDevice is saved."""
    if not getattr(settings, "USE_MULTITENANT", False):
        return

    current_schema = connection.schema_name
    if current_schema == get_public_schema_name():
        return

    from tenants.models import Client, EdgeDeviceIndex

    try:
        tenant = Client.objects.get(schema_name=current_schema)
    except Client.DoesNotExist:
        logger.warning("sync_edge_device_index_on_save: tenant %s not found", current_schema)
        return

    try:
        with schema_context(get_public_schema_name()):
            EdgeDeviceIndex.objects.update_or_create(
                edge_id=instance.id,
                defaults={
                    "tenant": tenant,
                    "tenant_schema": current_schema,
                    "edge_name": instance.name or "",
                    "is_active": instance.is_active,
                },
            )
    except Exception:
        logger.exception("Failed to sync EdgeDevice %s to public index", instance.id)


@receiver(post_delete, sender="scales.EdgeDevice")
def sync_edge_device_index_on_delete(sender, instance, **kwargs):
    """Remove public EdgeDeviceIndex when EdgeDevice is deleted."""
    if not getattr(settings, "USE_MULTITENANT", False):
        return

    from tenants.models import EdgeDeviceIndex

    try:
        with schema_context(get_public_schema_name()):
            EdgeDeviceIndex.objects.filter(edge_id=instance.id).delete()
    except Exception:
        logger.exception("Failed to remove EdgeDevice %s from public index", instance.id)


@receiver(post_save, sender="scales.DisassemblySession")
def bump_edge_sessions_cache_on_session_save(sender, instance, **kwargs):
    """Invalidate the /sessions payload cache on every DisassemblySession save.

    Mirrors labeling.signals._print_job_post_save_bump_cache: a single
    post_save hook catches every write path (edge ingest, web-UI event edit,
    session close, session cancel, reactivate, management commands, anything
    added later) instead of sprinkling explicit bump calls next to every
    save site.

    Audit on 2026-04-14 found that scales/views.py:1050 (close session) and
    :1067 (cancel session) both flip `status` — which IS in the edge /sessions
    payload — without calling _bump_edge_sessions_version. That left a stale
    cache window bounded only by _SESSIONS_PAYLOAD_TTL (2s) plus the edge's
    304 backoff, which can delay operator-visible state changes (like "close
    session" clearing the scale UI) by many seconds. This receiver closes
    that gap.

    Route: session → device → edge → edge_pk. Unbound sessions (no device)
    are ignored because they can't map to any edge's cache key.

    Cost: one cache.incr per session save. No-op if the session has no
    attached device. Bulk .filter().update() bypasses post_save — grep of
    DisassemblySession.objects.filter(...).update confirms no caller uses it,
    and any future bulk update must call _bump_edge_sessions_version(edge_pk)
    explicitly.
    """
    device = getattr(instance, "device", None)
    edge_id = getattr(device, "edge_id", None) if device else None
    if edge_id is None:
        return
    from scales.api_views import _bump_edge_sessions_version

    _bump_edge_sessions_version(edge_id)
