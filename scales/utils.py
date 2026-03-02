"""
Utilities for the scales app.
"""
import logging
import re
import uuid

from .models import PLUItem, WeighingEvent
from .plu_catalog import PLU_CATALOG

logger = logging.getLogger(__name__)


# UUID v4 pattern (8-4-4-4-12 hex, case-insensitive)
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def parse_animal_uuid_from_qr_url(url_or_uuid: str):
    """
    Parse animal UUID from a QR code URL or a plain UUID string.

    Accepts:
    - Full URL: https://domain.com/en/processing/animals/<uuid>/
    - Path-only: /en/processing/animals/<uuid>/
    - Plain UUID string

    Returns:
        uuid.UUID if a valid UUID is found, None otherwise.
    """
    if not url_or_uuid or not isinstance(url_or_uuid, str):
        logger.debug("[QR] parse_animal_uuid_from_qr_url: invalid input type=%s", type(url_or_uuid).__name__)
        return None
    text = url_or_uuid.strip()
    if not text:
        logger.debug("[QR] parse_animal_uuid_from_qr_url: empty after strip")
        return None
    match = UUID_PATTERN.search(text)
    if not match:
        logger.debug("[QR] parse_animal_uuid_from_qr_url: no UUID match in text (len=%d, preview=%r)", len(text), text[:80])
        return None
    try:
        result = uuid.UUID(match.group(0))
        logger.debug("[QR] parse_animal_uuid_from_qr_url: parsed uuid=%s from text (len=%d)", result, len(text))
        return result
    except (ValueError, TypeError) as e:
        logger.warning("[QR] parse_animal_uuid_from_qr_url: UUID validation failed match=%r error=%s", match.group(0), e)
        return None


def normalize_plu_code(plu_code):
    """
    Strip leading zeros from PLU code for catalog lookup.
    e.g. "000000000003" -> "3", "00003" -> "3"
    """
    if not plu_code or not isinstance(plu_code, str):
        return ""
    return plu_code.lstrip("0") or "0"


def get_embedded_plu_map():
    """
    Parse `scales/plu_catalog.py` into normalized PLU -> product name map.
    This file is the source of truth for cut naming.
    """
    catalog = {}
    for raw in (PLU_CATALOG or "").splitlines():
        line = (raw or "").strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        code, name = parts
        catalog[normalize_plu_code(code)] = name.strip()
    return catalog


def get_catalog_name_for_plu(plu_code):
    """Return product name from embedded PLU catalog (source of truth)."""
    norm = normalize_plu_code(plu_code)
    return get_embedded_plu_map().get(norm)


def get_product_display_names(plu_codes, site=None):
    """
    Resolve PLU codes to product names from PLUItem catalog.
    Strips leading zeros from PLU for lookup (e.g. "000000000003" matches "00003").
    Prefer site-specific PLUItem, then global (site=None), then any catalog entry (e.g. Default site).

    Args:
        plu_codes: iterable of plu_code strings (e.g. from scale: "000000000003")
        site: optional Site for site-specific lookup

    Returns:
        dict mapping original plu_code -> product name (PLUItem.name)
    """
    codes = list(set(c for c in plu_codes if c))
    if not codes:
        return {}

    # Build normalized -> plu_code mapping for lookup
    normalized_to_original = {normalize_plu_code(c): c for c in codes}
    normalized_codes = list(normalized_to_original.keys())

    # Source of truth first: embedded `scales/plu_catalog.py`.
    embedded = get_embedded_plu_map()
    result = {}
    for norm, original in normalized_to_original.items():
        if norm in embedded:
            result[original] = embedded[norm]

    # Then DB fallback for any missing codes.
    unresolved_norm = [n for n in normalized_codes if normalized_to_original[n] not in result]
    if not unresolved_norm:
        return result

    # Fetch ALL active PLUItems (catalog may be seeded to Default site; session may use different site)
    items = list(PLUItem.objects.filter(is_active=True))
    # Build normalized -> name map; first match wins, so process in priority order
    site_id = site.id if site else None
    catalog = {}
    # Pass 1: site-specific
    for item in items:
        n = normalize_plu_code(item.plu_code)
        if n in unresolved_norm and item.site_id == site_id and n not in catalog:
            catalog[n] = item.name
    # Pass 2: global (site=None)
    for item in items:
        n = normalize_plu_code(item.plu_code)
        if n in unresolved_norm and item.site_id is None and n not in catalog:
            catalog[n] = item.name
    # Pass 3: any remaining (e.g. Default site)
    for item in items:
        n = normalize_plu_code(item.plu_code)
        if n in unresolved_norm and n not in catalog:
            catalog[n] = item.name

    # Map unresolved plu_codes -> product name
    for norm, original in normalized_to_original.items():
        if original in result:
            continue
        if norm in catalog:
            result[original] = catalog[norm]
    return result


def get_event_allocation(event, session_animals_ordered):
    """
    Return allocated weight per animal for a single weighing event.

    - If event has assigned_animal (manual): that animal gets full weight_grams; others 0.
    - Otherwise (split): weight split evenly; remainder grams distributed deterministically
      by animal id order so total adds up exactly to weight_grams.

    Args:
        event: WeighingEvent with weight_grams, assigned_animal, allocation_mode.
        session_animals_ordered: list of Animal (or id) in stable order for remainder.

    Returns:
        dict mapping animal_id (str UUID) -> allocated weight in grams (int).
    """
    weight = event.weight_grams or 0
    animal_ids = [str(getattr(a, "id", a)) for a in session_animals_ordered]
    out = {aid: 0 for aid in animal_ids}

    if not animal_ids:
        return out

    assigned_id = getattr(event, "assigned_animal_id", None)
    if not assigned_id and getattr(event, "assigned_animal", None):
        assigned_id = event.assigned_animal.id
    if assigned_id:
        aid = str(assigned_id)
        if aid in out:
            out[aid] = weight
        return out

    n = len(animal_ids)
    base = weight // n
    remainder = weight % n
    for i, aid in enumerate(animal_ids):
        out[aid] = base + (1 if i < remainder else 0)
    return out


def get_session_per_animal_summary(session):
    """
    Compute per-animal allocated totals and averages for a session.

    Uses get_event_allocation for each active, non-deleted event; aggregates by animal.
    Effective event count for an animal: each manual event assigned to it counts 1;
    each split event counts 1/n (so sum can be fractional).

    Args:
        session: DisassemblySession with events and animals.

    Returns:
        list of dicts: {
            "animal": Animal,
            "total_allocated_grams": int,
            "effective_event_count": float,
            "average_grams": float or None (if no events),
        } ordered by animal id.
    """
    animals = list(session.animals.order_by("id"))
    if not animals:
        if session.animal_id:
            animals = [session.animal]
        else:
            return []

    events = list(
        WeighingEvent.objects.filter(
            session=session, is_active=True, deleted_at__isnull=True
        ).order_by("scale_timestamp")
    )

    totals = {str(a.id): 0 for a in animals}
    effective_count = {str(a.id): 0.0 for a in animals}
    n_animals = len(animals)

    for ev in events:
        alloc = get_event_allocation(ev, animals)
        assigned_id = getattr(ev, "assigned_animal_id", None) or (ev.assigned_animal.id if getattr(ev, "assigned_animal", None) else None)
        for aid, grams in alloc.items():
            if aid not in totals:
                continue
            totals[aid] += grams
            if assigned_id and str(assigned_id) == aid:
                effective_count[aid] += 1.0
            else:
                effective_count[aid] += 1.0 / n_animals if n_animals else 0

    result = []
    for a in animals:
        aid = str(a.id)
        total = totals.get(aid, 0)
        eff = effective_count.get(aid, 0) or 0
        avg = round(total / eff, 2) if eff else None
        result.append({
            "animal": a,
            "total_allocated_grams": total,
            "effective_event_count": round(eff, 2),
            "average_grams": avg,
        })
    return result


def get_event_linked_animals(event):
    """
    Return animals linked to an event for status updates.

    Priority:
    - manual assignment (`assigned_animal`)
    - session animals M2M / fallback legacy `session.animal`
    - event legacy `animal`
    """
    if not event:
        return []

    if getattr(event, "assigned_animal_id", None):
        return [event.assigned_animal]

    session = getattr(event, "session", None)
    if session:
        animals = list(session.animals.order_by("id"))
        if animals:
            return animals
        if session.animal_id:
            return [session.animal]

    if getattr(event, "animal_id", None):
        return [event.animal]
    return []


def maybe_mark_event_animals_disassembled(event):
    """
    Transition linked animals from carcass_ready -> disassembled when eligible.

    This is a best-effort helper: failures are logged and never break event flows.
    """
    transitioned_ids = []
    seen = set()
    for animal in get_event_linked_animals(event):
        if not animal:
            continue
        aid = str(animal.id)
        if aid in seen:
            continue
        seen.add(aid)

        if animal.status != "carcass_ready":
            continue
        try:
            readiness = animal.can_proceed_to_disassembly()
            if readiness.get("can_proceed"):
                animal.perform_disassembly()
                animal.save()
                transitioned_ids.append(aid)
        except Exception as exc:
            logger.warning(
                "Failed auto disassembly transition for animal %s from scale event %s: %s",
                aid,
                getattr(event, "id", None),
                exc,
            )
    return transitioned_ids
