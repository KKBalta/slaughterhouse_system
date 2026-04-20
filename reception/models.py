from django.db import models
from django.utils import timezone

from core.models import BaseModel, ServicePackage
from users.models import ClientProfile


class SlaughterOrder(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        BILLED = "BILLED", "Billed"
        CANCELLED = "CANCELLED", "Cancelled"

    slaughter_order_no = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text="A human-readable, unique order number. Automatically generated if not provided.",
    )
    # For registered clients
    client = models.ForeignKey(
        ClientProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="slaughter_orders"
    )
    destination_client = models.ForeignKey(
        ClientProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="destination_orders",
        help_text="Destination client selected for this order.",
    )

    # For walk-in clients
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=20, blank=True)

    service_package = models.ForeignKey(
        ServicePackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slaughter_orders",
        help_text="The service package selected for this order.",
    )

    order_datetime = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    destination = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Specifies the final destination or market for the animals/products in this order.",
    )

    def save(self, *args, **kwargs):
        """
        Auto-generate unique order number if not provided.

        For production code paths use create_slaughter_order() in services. This
        method remains for admin / direct ORM use and retries only on the
        slaughter_order_no unique-violation so unrelated IntegrityErrors surface.
        """
        from django.db import IntegrityError, transaction

        if self.slaughter_order_no:
            super().save(*args, **kwargs)
            return

        from .services import MAX_ORDER_CREATION_RETRIES, _is_slaughter_order_no_unique_violation, generate_order_number

        last_exception = None
        for _attempt in range(MAX_ORDER_CREATION_RETRIES):
            try:
                with transaction.atomic():
                    self.slaughter_order_no = generate_order_number(self.order_datetime)
                    super().save(*args, **kwargs)
                return
            except IntegrityError as e:
                if not _is_slaughter_order_no_unique_violation(e):
                    raise
                self.slaughter_order_no = None
                last_exception = e
                continue

        raise IntegrityError(
            f"Failed to save order after {MAX_ORDER_CREATION_RETRIES} attempts. Last error: {last_exception}"
        )

    def __str__(self):
        client_display = self.client.company_name if self.client else self.client_name
        order_date = self.order_datetime.date() if hasattr(self.order_datetime, "date") else self.order_datetime
        return f"Order {self.slaughter_order_no} for {client_display} on {order_date}"
