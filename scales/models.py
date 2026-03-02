"""
Scale operations models for CarniTrack Edge integration.
Bridges Edge devices, scale devices, sessions, and weighing events to processing.Animal.
"""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext as _

from core.models import BaseModel


class Site(BaseModel):
    """Multi-tenant: different butcher shops/plants."""

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    api_key = models.CharField(max_length=100, unique=True, blank=True, null=True)

    def __str__(self):
        return self.name


class EdgeDevice(BaseModel):
    """Edge computers registered with Cloud (CarniTrack Edge)."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="edges")
    name = models.CharField(max_length=200, blank=True)
    is_online = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    version = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.name or str(self.id)[:8]} ({self.site.name})"


class ScaleDevice(BaseModel):
    """DP-401 scales connected to Edges."""

    edge = models.ForeignKey(EdgeDevice, on_delete=models.CASCADE, related_name="scales")
    device_id = models.CharField(max_length=50)  # e.g. "SCALE-01" (local to site)
    global_device_id = models.CharField(max_length=100, unique=True)  # e.g. "SITE01-SCALE-01"
    name = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    device_type = models.CharField(max_length=50, default="disassembly")  # disassembly | retail | receiving
    status = models.CharField(max_length=50, default="unknown")  # online | idle | stale | disconnected | unknown
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["edge", "device_id"], name="scales_scaledevice_edge_device_id")]

    def __str__(self):
        return f"{self.device_id} @ {self.edge.name or self.edge.id}"


class PLUItem(BaseModel):
    """Master product catalog for scale PLU codes (seeded from plu_clean.txt)."""

    CATEGORY_CHOICES = [
        ("Dana", "Dana"),
        ("Kuzu", "Kuzu"),
        ("Koyun", "Koyun"),
        ("Oglak", "Oglak"),
        ("Genel", "Genel"),
    ]
    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name="plu_items", null=True, blank=True
    )  # null for global PLU catalog (single-site)
    plu_code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    name_turkish = models.CharField(max_length=16, blank=True)  # 16-char limit for scale label
    barcode = models.CharField(max_length=50, blank=True)
    price_cents = models.IntegerField(default=0)
    unit_type = models.CharField(max_length=10, default="kg")  # kg | piece
    tare_grams = models.IntegerField(default=0)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default="Genel")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "plu_code"],
                name="scales_pluitem_site_plu",
            )
        ]

    def __str__(self):
        return f"{self.plu_code} - {self.name}"


class DisassemblySession(BaseModel):
    """Session linking scale events to one or more animals — source of truth for Edge."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("auto_closed", "Auto-closed"),
    ]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="scale_sessions")
    animal = models.ForeignKey(
        "processing.Animal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scale_sessions",
    )
    animals = models.ManyToManyField(
        "processing.Animal",
        related_name="disassembly_session_animals",
        blank=True,
        help_text="All animals in this session (multi-animal scaling).",
    )
    device = models.ForeignKey(
        ScaleDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )
    operator = models.CharField(max_length=100)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    total_weight_grams = models.IntegerField(default=0)
    event_count = models.IntegerField(default=0)
    close_reason = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device"],
                condition=Q(
                    device__isnull=False,
                    status__in=["pending", "active", "paused"],
                    is_active=True,
                ),
                name="unique_active_session_per_device",
            ),
        ]

    def get_primary_animal(self):
        """First animal for backward compatibility; prefers animal FK then first in animals."""
        if self.animal_id:
            return self.animal
        return self.animals.order_by("id").first()

    def get_short_session_code(self):
        """Human-friendly session ID: S-YYYYMMDD-XXXXXX (date from started_at, 6 chars of UUID)."""
        date_part = self.started_at.strftime("%Y%m%d") if self.started_at else "00000000"
        uuid_part = str(self.id).replace("-", "")[:6] if self.id else "------"
        return f"S-{date_part}-{uuid_part}"

    def get_animals_summary(self, limit=2):
        """Localized tag summary: single tag, first N tags + '+M more', or 'No animals'."""
        animals = sorted(self.animals.all(), key=lambda a: a.id or 0)
        tags = [a.identification_tag or "—" for a in animals]
        if not tags and self.animal_id:
            tag = self.animal.identification_tag if self.animal else None
            tags = [tag or "—"] if tag else []
        if not tags:
            return _("No animals")
        if len(tags) == 1:
            return tags[0]
        shown = tags[:limit]
        rest = len(tags) - limit
        if rest > 0:
            return ", ".join(shown) + " " + _("+%(count)s more") % {"count": rest}
        return ", ".join(shown)

    def __str__(self):
        primary = self.get_primary_animal()
        if primary:
            animal_str = primary.identification_tag
            count = self.animals.count()
            if count > 1:
                animal_str = f"{animal_str} +{count - 1}"
        else:
            animal_str = "No animal"
        return f"Session {str(self.id)[:8]} - {animal_str} ({self.status})"


class WeighingEvent(BaseModel):
    """Individual weighing/print events from scales."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="weighing_events")
    session = models.ForeignKey(
        DisassemblySession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    device = models.ForeignKey(
        ScaleDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    animal = models.ForeignKey(
        "processing.Animal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weighing_events",
    )
    ALLOCATION_MODES = [
        ("split", "Split"),
        ("manual", "Manual"),
    ]
    allocation_mode = models.CharField(max_length=20, choices=ALLOCATION_MODES, default="split")
    assigned_animal = models.ForeignKey(
        "processing.Animal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weighing_events_assigned",
        help_text="When set (manual mode), this event is fully allocated to this animal.",
    )
    allocated_weight_grams = models.IntegerField(
        null=True, blank=True, help_text="Cached weight allocated to assigned_animal for display."
    )
    plu_code = models.CharField(max_length=20)
    product_name = models.CharField(max_length=100)
    product_display_override = models.CharField(
        max_length=100, blank=True
    )  # Manual override for display; when set, used instead of catalog
    weight_grams = models.IntegerField()
    barcode = models.CharField(max_length=50)
    scale_timestamp = models.DateTimeField()
    edge_received_at = models.DateTimeField()
    cloud_received_at = models.DateTimeField(auto_now_add=True)
    edge_event_id = models.CharField(max_length=100, unique=True)  # localEventId from Edge (dedup key)
    offline_batch_id = models.CharField(max_length=100, blank=True, null=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "scale_timestamp"]),
            models.Index(fields=["session"]),
            models.Index(fields=["animal"]),
            models.Index(fields=["assigned_animal"]),
            models.Index(fields=["offline_batch_id"]),
            models.Index(fields=["edge_event_id"]),
        ]

    def __str__(self):
        dev = self.device.device_id if self.device else "?"
        return f"{dev} | {self.plu_code} | {self.weight_grams}g"


class OrphanedBatch(BaseModel):
    """Batches of events captured while Edge was offline, pending reconciliation."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("reconciled", "Reconciled"),
        ("ignored", "Ignored"),
    ]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="orphaned_batches")
    edge = models.ForeignKey(EdgeDevice, on_delete=models.CASCADE, related_name="orphaned_batches")
    device = models.ForeignKey(
        ScaleDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orphaned_batches",
    )
    batch_id = models.CharField(max_length=100, unique=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    event_count = models.IntegerField(default=0)
    total_weight_grams = models.IntegerField(default=0)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="pending")
    reconciled_to_session = models.ForeignKey(
        DisassemblySession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciled_batches",
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"Batch {self.batch_id} ({self.status}, {self.event_count} events)"


class OfflineBatchAck(BaseModel):
    """Tracks offline batch ACKs for idempotency. Edge sends ACK after uploading events."""

    batch_id = models.CharField(max_length=100, unique=True, db_index=True)
    received_at = models.DateTimeField()
    edge = models.ForeignKey(
        EdgeDevice,
        on_delete=models.CASCADE,
        related_name="batch_acks",
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="batch_acks",
        null=True,
        blank=True,
    )
    device_id = models.CharField(max_length=50, blank=True)
    event_count = models.IntegerField(null=True, blank=True)
    total_weight_grams = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"Batch ACK {self.batch_id} @ {self.received_at.isoformat()}"


class EdgeActivityLog(BaseModel):
    """Operational audit log for edge API interactions and state changes."""

    LEVEL_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
    ]

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="edge_activity_logs",
        null=True,
        blank=True,
    )
    edge = models.ForeignKey(
        EdgeDevice,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    device = models.ForeignKey(
        ScaleDevice,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default="info")
    action = models.CharField(max_length=50)
    message = models.CharField(max_length=255)
    request_path = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["site", "-created_at"]),
            models.Index(fields=["edge", "-created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["level"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        edge_name = self.edge.name if self.edge and self.edge.name else str(self.edge_id or "-")
        return f"{self.action} [{self.level}] {edge_name}"
