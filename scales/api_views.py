"""
Edge API views — JSON endpoints called by CarniTrack Edge (Bun).
Contract per DJANGO_CLOUD_INTEGRATION_SPEC.md.
"""
import hashlib
import json
import uuid
from datetime import datetime
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt

from .models import (
    Site,
    EdgeDevice,
    ScaleDevice,
    DisassemblySession,
    WeighingEvent,
    OrphanedBatch,
    OfflineBatchAck,
    EdgeActivityLog,
)
from .middleware import require_edge_id, parse_json_body
from .utils import maybe_mark_event_animals_disassembled

# Default config returned to Edge
DEFAULT_CONFIG = {
    "sessionPollIntervalMs": 5000,
    "heartbeatIntervalMs": 30000,
    "workHoursStart": "06:00",
    "workHoursEnd": "18:00",
    "timezone": "Europe/Istanbul",
}


def _parse_iso(s):
    """Parse ISO 8601 string to datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _parse_uuid(value):
    """Return UUID object or None if value is not a valid UUID string."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _species_for_animal(animal):
    """Map processing.Animal.animal_type to spec species name (Kuzu, Dana, Koyun, etc.)."""
    if not animal:
        return None
    m = {
        "cattle": "Dana",
        "beef": "Sığır",
        "calf": "Dana",
        "heifer": "Düve",
        "sheep": "Koyun",
        "lamb": "Kuzu",
        "goat": "Keçi",
        "oglak": "Oğlak",
    }
    return m.get(animal.animal_type) or animal.get_animal_type_display()


def _log_edge_activity(
    *,
    action,
    message,
    level="info",
    request=None,
    edge=None,
    site=None,
    device=None,
    payload=None,
):
    """Best-effort logging that never breaks API responses."""
    try:
        if request is not None:
            request_path = request.path
            edge = edge or getattr(request, "edge_device", None)
            site = site or getattr(request, "edge_site", None)
        else:
            request_path = ""
        EdgeActivityLog.objects.create(
            site=site,
            edge=edge,
            device=device,
            level=level,
            action=action,
            message=message[:255],
            request_path=request_path[:255],
            payload=payload or {},
        )
    except Exception:
        # Keep edge API endpoints resilient even if logging fails.
        pass


# ---------- POST /register (no auth; first call has edgeId=null) ----------
@csrf_exempt
@parse_json_body
def edge_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    body = request.json_body
    edge_id_raw = body.get("edgeId")
    site_id_raw = body.get("siteId")
    site_name = (body.get("siteName") or "").strip() or "Default Site"
    version = (body.get("version") or "").strip()

    if edge_id_raw:
        # Re-registration: update existing edge
        edge_uuid = _parse_uuid(edge_id_raw)
        if not edge_uuid:
            return JsonResponse(
                {"error": "Invalid edgeId format; expected UUID from /edge/register"},
                status=400,
            )
        try:
            edge = EdgeDevice.objects.get(id=edge_uuid, is_active=True)
        except (EdgeDevice.DoesNotExist, ValueError, ValidationError):
            return JsonResponse({"error": "Edge not found"}, status=404)
        edge.is_online = True
        edge.last_seen_at = timezone.now()
        if version:
            edge.version = version
        if site_name and not edge.site.name:
            edge.site.name = site_name
            edge.site.save(update_fields=["name", "updated_at"])
        edge.save(update_fields=["is_online", "last_seen_at", "version", "updated_at"])
        site = edge.site
        _log_edge_activity(
            action="register",
            request=request,
            edge=edge,
            site=site,
            message=f"Edge re-registered: {edge.id}",
            payload={"version": version or edge.version, "mode": "reregister"},
        )
    else:
        # First registration: create site and edge
        site = Site.objects.filter(name=site_name).first()
        if not site:
            site = Site.objects.create(
                name=site_name,
                address="",
            )
        elif site_id_raw and str(site.id) != str(site_id_raw):
            pass  # keep existing site
        edge = EdgeDevice.objects.create(
            site=site,
            name=site_name,
            is_online=True,
            last_seen_at=timezone.now(),
            version=version or "",
        )
        _log_edge_activity(
            action="register",
            request=request,
            edge=edge,
            site=site,
            message=f"Edge registered: {edge.id}",
            payload={"version": version, "mode": "first_registration"},
        )

    return JsonResponse({
        "edgeId": str(edge.id),
        "siteId": str(site.id),
        "siteName": site.name,
        "config": DEFAULT_CONFIG,
    })


def _compute_sessions_etag(payload):
    """Compute ETag from sessions payload for conditional GET."""
    payload_str = json.dumps(payload, sort_keys=True)
    hash_val = hashlib.md5(payload_str.encode()).hexdigest()[:16]
    return f'"sessions-{hash_val}"'


def _sessions_response_with_etag(request, payload, etag):
    """Return 304 if client ETag matches, else 200 with payload and ETag headers."""
    client_etag = request.META.get("HTTP_IF_NONE_MATCH", "").strip()
    if client_etag == etag:
        response = HttpResponse(status=304)
        response["ETag"] = etag
        response["Cache-Control"] = "no-cache"
        return response
    response = JsonResponse(payload)
    response["ETag"] = etag
    response["Cache-Control"] = "no-cache"
    return response


# ---------- GET /sessions ----------
@csrf_exempt
@require_edge_id
def edge_sessions(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    request.edge_device.last_seen_at = timezone.now()
    request.edge_device.save(update_fields=["last_seen_at", "updated_at"])
    device_ids_param = request.GET.get("device_ids", "")
    device_ids = [d.strip() for d in device_ids_param.split(",") if d.strip()]
    if not device_ids:
        _log_edge_activity(
            action="sessions_poll",
            request=request,
            message="Session poll with empty device list",
            level="warning",
        )
        payload = {"sessions": []}
        etag = _compute_sessions_etag(payload)
        return _sessions_response_with_etag(request, payload, etag)

    sessions = (
        DisassemblySession.objects.filter(
            device__edge=request.edge_device,
            device__device_id__in=device_ids,
            status__in=["pending", "active", "paused"],
            is_active=True,
        )
        .select_related("device", "animal")
    )
    out = []
    for s in sessions:
        animal = s.animal
        out.append({
            "cloudSessionId": str(s.id),
            "deviceId": s.device.device_id if s.device else "",
            "animalId": str(animal.id) if animal else None,
            "animalTag": animal.identification_tag if animal else None,
            "animalSpecies": _species_for_animal(animal) if animal else None,
            "operatorId": s.operator or None,
            "status": s.status if s.status in {"pending", "active", "paused"} else "paused",
        })
    _log_edge_activity(
        action="sessions_poll",
        request=request,
        message=f"Session poll returned {len(out)} session(s)",
        payload={"device_ids": device_ids, "session_count": len(out)},
    )
    payload = {"sessions": out}
    etag = _compute_sessions_etag(payload)
    return _sessions_response_with_etag(request, payload, etag)


# ---------- POST /events (single) ----------
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_post_event(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    body = request.json_body
    local_event_id = body.get("localEventId")
    device_id = body.get("deviceId")
    global_device_id = body.get("globalDeviceId") or ""
    cloud_session_id = body.get("cloudSessionId")
    offline_mode = body.get("offlineMode", False)
    offline_batch_id = body.get("offlineBatchId")
    plu_code = body.get("pluCode", "").strip()
    product_name = (body.get("productName") or "").strip()
    weight_grams = body.get("weightGrams", 0)
    barcode = (body.get("barcode") or "").strip()
    scale_ts = _parse_iso(body.get("scaleTimestamp"))
    received_ts = _parse_iso(body.get("receivedAt"))

    if not local_event_id:
        return JsonResponse({"error": "localEventId required"}, status=400)
    if scale_ts is None:
        scale_ts = timezone.now()
    if received_ts is None:
        received_ts = timezone.now()

    # Deduplicate
    existing = WeighingEvent.objects.filter(edge_event_id=local_event_id).first()
    if existing:
        _log_edge_activity(
            action="event_duplicate",
            request=request,
            message=f"Duplicate edge event skipped: {local_event_id}",
            payload={"localEventId": local_event_id},
        )
        return JsonResponse({
            "cloudEventId": str(existing.id),
            "status": "duplicate",
        })

    # Resolve scale device (create if needed for this edge)
    scale_device = ScaleDevice.objects.filter(
        edge=request.edge_device,
        device_id=device_id,
    ).first()
    if not scale_device:
        scale_device = ScaleDevice.objects.create(
            edge=request.edge_device,
            device_id=device_id,
            global_device_id=global_device_id or f"{request.edge_device.id}-{device_id}",
            device_type="disassembly",
            status="online",
        )
        _log_edge_activity(
            action="device_autocreate",
            request=request,
            edge=request.edge_device,
            site=request.edge_site,
            device=scale_device,
            message=f"Scale device auto-created: {device_id}",
            payload={"globalDeviceId": scale_device.global_device_id},
        )

    site = request.edge_site
    session = None
    if cloud_session_id:
        try:
            session = DisassemblySession.objects.get(
                id=cloud_session_id,
                site=site,
                is_active=True,
            )
        except (DisassemblySession.DoesNotExist, ValueError):
            pass

    animal = session.get_primary_animal() if session else None

    event = WeighingEvent.objects.create(
        site=site,
        session=session,
        device=scale_device,
        animal=animal,
        allocation_mode="split",
        plu_code=plu_code,
        product_name=product_name[:100],
        weight_grams=int(weight_grams),
        barcode=barcode[:50],
        scale_timestamp=scale_ts,
        edge_received_at=received_ts,
        edge_event_id=local_event_id,
        offline_batch_id=offline_batch_id or None,
    )
    maybe_mark_event_animals_disassembled(event)

    if session:
        session.total_weight_grams += int(weight_grams)
        session.event_count += 1
        session.last_event_at = timezone.now()
        if session.status == "pending":
            session.status = "active"
        session.save(update_fields=["total_weight_grams", "event_count", "last_event_at", "status", "updated_at"])

    if offline_mode and offline_batch_id:
        batch, _ = OrphanedBatch.objects.get_or_create(
            batch_id=offline_batch_id,
            defaults={
                "site": site,
                "edge": request.edge_device,
                "device": scale_device,
                "started_at": scale_ts,
                "status": "pending",
                "event_count": 0,
                "total_weight_grams": 0,
            },
        )
        batch.event_count += 1
        batch.total_weight_grams += int(weight_grams)
        batch.ended_at = timezone.now()
        batch.save(update_fields=["event_count", "total_weight_grams", "ended_at", "updated_at"])
        _log_edge_activity(
            action="offline_batch_update",
            request=request,
            edge=request.edge_device,
            site=site,
            device=scale_device,
            message=f"Offline batch updated: {offline_batch_id}",
            payload={"batch_id": offline_batch_id, "event_count": batch.event_count},
        )

    _log_edge_activity(
        action="event_accepted",
        request=request,
        edge=request.edge_device,
        site=site,
        device=scale_device,
        message=f"Weight event accepted: {local_event_id}",
        payload={
            "localEventId": local_event_id,
            "sessionId": str(session.id) if session else None,
            "deviceId": device_id,
            "weightGrams": int(weight_grams),
        },
    )

    return JsonResponse({
        "cloudEventId": str(event.id),
        "status": "accepted",
    })


# ---------- POST /events/batch ----------
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_post_event_batch(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    events = request.json_body.get("events") or []
    results = []

    for ev in events:
        local_event_id = ev.get("localEventId")
        device_id = ev.get("deviceId")
        global_device_id = ev.get("globalDeviceId") or ""
        cloud_session_id = ev.get("cloudSessionId")
        offline_mode = ev.get("offlineMode", False)
        offline_batch_id = ev.get("offlineBatchId")
        plu_code = (ev.get("pluCode") or "").strip()
        product_name = (ev.get("productName") or "").strip()
        weight_grams = ev.get("weightGrams", 0)
        barcode = (ev.get("barcode") or "").strip()
        scale_ts = _parse_iso(ev.get("scaleTimestamp"))
        received_ts = _parse_iso(ev.get("receivedAt"))

        if not local_event_id:
            results.append({
                "localEventId": "",
                "cloudEventId": "",
                "status": "failed",
                "error": "localEventId required",
            })
            continue

        if scale_ts is None:
            scale_ts = timezone.now()
        if received_ts is None:
            received_ts = timezone.now()

        try:
            with transaction.atomic():
                existing = WeighingEvent.objects.filter(edge_event_id=local_event_id).first()
                if existing:
                    results.append({
                        "localEventId": local_event_id,
                        "cloudEventId": str(existing.id),
                        "status": "duplicate",
                    })
                    continue

                scale_device = ScaleDevice.objects.filter(
                    edge=request.edge_device,
                    device_id=device_id,
                ).first()
                if not scale_device:
                    scale_device = ScaleDevice.objects.create(
                        edge=request.edge_device,
                        device_id=device_id,
                        global_device_id=global_device_id or f"{request.edge_device.id}-{device_id}",
                        device_type="disassembly",
                        status="online",
                    )

                site = request.edge_site
                session = None
                if cloud_session_id:
                    try:
                        session = DisassemblySession.objects.get(
                            id=cloud_session_id,
                            site=site,
                            is_active=True,
                        )
                    except (DisassemblySession.DoesNotExist, ValueError):
                        pass

                animal = session.get_primary_animal() if session else None

                event = WeighingEvent.objects.create(
                    site=site,
                    session=session,
                    device=scale_device,
                    animal=animal,
                    allocation_mode="split",
                    plu_code=plu_code,
                    product_name=product_name[:100],
                    weight_grams=int(weight_grams),
                    barcode=barcode[:50],
                    scale_timestamp=scale_ts,
                    edge_received_at=received_ts,
                    edge_event_id=local_event_id,
                    offline_batch_id=offline_batch_id or None,
                )
                maybe_mark_event_animals_disassembled(event)

                if session:
                    session.total_weight_grams += int(weight_grams)
                    session.event_count += 1
                    session.last_event_at = timezone.now()
                    if session.status == "pending":
                        session.status = "active"
                    session.save(update_fields=["total_weight_grams", "event_count", "last_event_at", "status", "updated_at"])

                if offline_mode and offline_batch_id:
                    batch, _ = OrphanedBatch.objects.get_or_create(
                        batch_id=offline_batch_id,
                        defaults={
                            "site": site,
                            "edge": request.edge_device,
                            "device": scale_device,
                            "started_at": scale_ts,
                            "status": "pending",
                            "event_count": 0,
                            "total_weight_grams": 0,
                        },
                    )
                    batch.event_count += 1
                    batch.total_weight_grams += int(weight_grams)
                    batch.ended_at = timezone.now()
                    batch.save(update_fields=["event_count", "total_weight_grams", "ended_at", "updated_at"])

                results.append({
                    "localEventId": local_event_id,
                    "cloudEventId": str(event.id),
                    "status": "accepted",
                })
        except Exception as e:
            results.append({
                "localEventId": local_event_id,
                "cloudEventId": "",
                "status": "failed",
                "error": str(e),
            })

    accepted = sum(1 for row in results if row.get("status") == "accepted")
    duplicate = sum(1 for row in results if row.get("status") == "duplicate")
    failed = sum(1 for row in results if row.get("status") == "failed")
    _log_edge_activity(
        action="event_batch_processed",
        request=request,
        message=f"Batch processed: {accepted} accepted, {duplicate} duplicate, {failed} failed",
        level="warning" if failed else "info",
        payload={
            "accepted": accepted,
            "duplicate": duplicate,
            "failed": failed,
            "total": len(results),
        },
    )
    return JsonResponse({"results": results})


# ---------- POST /offline-batches/ack ----------
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_offline_batch_ack(request):
    """
    Idempotent offline batch ACK. Edge sends this after successfully uploading
    events for an offline batch. Cloud acknowledges receipt so Edge can mark
    the batch as reconciled and stop retrying.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    body = request.json_body
    batch_id = (body.get("batchId") or "").strip()
    device_id = (body.get("deviceId") or "").strip()
    event_ids = body.get("eventIds") or []
    event_count = body.get("eventCount")
    total_weight_grams = body.get("totalWeightGrams")
    started_at = _parse_iso(body.get("startedAt"))
    ended_at = _parse_iso(body.get("endedAt"))

    if not batch_id:
        return JsonResponse({"error": "batchId required"}, status=400)

    now = timezone.now()

    existing = OfflineBatchAck.objects.filter(batch_id=batch_id).first()
    if existing:
        _log_edge_activity(
            action="offline_batch_ack_duplicate",
            request=request,
            message=f"Duplicate batch ACK: {batch_id}",
            payload={"batchId": batch_id},
        )
        return JsonResponse({
            "batchId": batch_id,
            "status": "already_received",
            "receivedAt": existing.received_at.isoformat(),
        })

    OfflineBatchAck.objects.create(
        batch_id=batch_id,
        received_at=now,
        edge=request.edge_device,
        site=request.edge_site,
        device_id=device_id or "",
        event_count=event_count if event_count is not None else None,
        total_weight_grams=total_weight_grams if total_weight_grams is not None else None,
        started_at=started_at,
        ended_at=ended_at,
    )

    _log_edge_activity(
        action="offline_batch_ack",
        request=request,
        message=f"Batch ACK received: {batch_id}",
        payload={
            "batchId": batch_id,
            "deviceId": device_id,
            "eventCount": event_count,
            "eventIdsCount": len(event_ids),
        },
    )

    return JsonResponse({
        "batchId": batch_id,
        "status": "received",
        "receivedAt": now.isoformat(),
    })


# ---------- GET /config ----------
@csrf_exempt
@require_edge_id
def edge_config(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    edge = request.edge_device
    edge.last_seen_at = timezone.now()
    edge.save(update_fields=["last_seen_at", "updated_at"])
    payload = {
        "edgeId": str(edge.id),
        "sessionPollIntervalMs": DEFAULT_CONFIG["sessionPollIntervalMs"],
        "heartbeatIntervalMs": DEFAULT_CONFIG["heartbeatIntervalMs"],
        "workHoursStart": DEFAULT_CONFIG["workHoursStart"],
        "workHoursEnd": DEFAULT_CONFIG["workHoursEnd"],
        "timezone": DEFAULT_CONFIG["timezone"],
    }
    return JsonResponse(payload)


# ---------- POST /devices/status ----------
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_device_status(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    body = request.json_body
    device_id = body.get("deviceId")
    status_val = body.get("status", "unknown")
    global_device_id = body.get("globalDeviceId") or ""
    device_type = body.get("deviceType", "disassembly")
    ts = _parse_iso(body.get("timestamp")) or timezone.now()

    if not device_id:
        return JsonResponse({"error": "deviceId required"}, status=400)

    scale_device = ScaleDevice.objects.filter(
        edge=request.edge_device,
        device_id=device_id,
    ).first()
    if not scale_device:
        scale_device = ScaleDevice.objects.create(
            edge=request.edge_device,
            device_id=device_id,
            global_device_id=global_device_id or f"{request.edge_device.id}-{device_id}",
            device_type=device_type,
            status=status_val,
        )
        _log_edge_activity(
            action="device_status",
            request=request,
            edge=request.edge_device,
            site=request.edge_site,
            device=scale_device,
            message=f"Device status created: {device_id} -> {status_val}",
            payload={"deviceType": device_type, "status": status_val},
        )
    else:
        scale_device.status = status_val
        scale_device.device_type = device_type or scale_device.device_type
        if status_val == "online":
            scale_device.last_heartbeat_at = ts
        scale_device.save(update_fields=["status", "device_type", "last_heartbeat_at", "updated_at"])
        _log_edge_activity(
            action="device_status",
            request=request,
            edge=request.edge_device,
            site=request.edge_site,
            device=scale_device,
            message=f"Device status updated: {device_id} -> {status_val}",
            payload={"deviceType": device_type, "status": status_val},
        )

    return JsonResponse({"ok": True})


# ---------- POST /heartbeat (aggregated edge + devices connectivity) ----------
@csrf_exempt
@require_edge_id
@parse_json_body
def edge_heartbeat(request):
    """Accept full connectivity snapshot: edge + printers in one request."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    edge = request.edge_device
    edge.is_online = True
    edge.last_seen_at = timezone.now()
    update_fields = ["is_online", "last_seen_at", "updated_at"]
    body = request.json_body
    if body.get("version"):
        edge.version = (body.get("version") or "")[:20]
        update_fields.append("version")
    edge.save(update_fields=update_fields)

    devices_payload = body.get("devices") or []
    device_summary = []
    for item in devices_payload:
        device_id = item.get("deviceId")
        if not device_id:
            continue
        global_device_id = (item.get("globalDeviceId") or "").strip() or f"{edge.id}-{device_id}"
        device_type = (item.get("deviceType") or "disassembly").strip() or "disassembly"
        status = (item.get("status") or "unknown").strip() or "unknown"
        last_heartbeat_at = _parse_iso(item.get("lastHeartbeatAt")) or timezone.now()
        last_event_at = _parse_iso(item.get("lastEventAt"))

        scale_device, created = ScaleDevice.objects.get_or_create(
            edge=edge,
            device_id=device_id,
            defaults={
                "global_device_id": global_device_id,
                "device_type": device_type,
                "status": status,
                "last_heartbeat_at": last_heartbeat_at,
                "last_event_at": last_event_at,
            },
        )
        if not created:
            scale_device.status = status
            scale_device.device_type = device_type
            scale_device.last_heartbeat_at = last_heartbeat_at
            if last_event_at is not None:
                scale_device.last_event_at = last_event_at
            scale_device.save(
                update_fields=["status", "device_type", "last_heartbeat_at", "last_event_at", "updated_at"]
            )
        device_summary.append({"deviceId": device_id, "status": status})

    _log_edge_activity(
        action="heartbeat",
        request=request,
        edge=edge,
        site=request.edge_site,
        message=f"Heartbeat: {len(device_summary)} device(s)",
        payload={"devices": device_summary[:20]},
    )

    return JsonResponse({
        "ok": True,
        "serverTime": timezone.now().isoformat(),
    })
