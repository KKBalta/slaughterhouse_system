from django.db import models
from core.models import BaseModel, ServicePackage
from users.models import ClientProfile
from django.utils import timezone
import datetime

class SlaughterOrder(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", 'Pending'
        IN_PROGRESS = "IN_PROGRESS", 'In Progress'
        COMPLETED = "COMPLETED", 'Completed'
        BILLED = "BILLED", 'Billed'
        CANCELLED = "CANCELLED", 'Cancelled'

    slaughter_order_no = models.CharField(
        max_length=50,
        unique=True,
        blank=True, null=True,
        help_text="A human-readable, unique order number. Automatically generated if not provided."
    )
    # For registered clients
    client = models.ForeignKey(ClientProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='slaughter_orders')

    # For walk-in clients
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=20, blank=True)

    service_package = models.ForeignKey(
        ServicePackage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='slaughter_orders',
        help_text="The service package selected for this order."
    )

    order_datetime = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    destination = models.CharField(
        max_length=255,
        blank=True, null=True,
        help_text="Specifies the final destination or market for the animals/products in this order."
    )

    def save(self, *args, **kwargs):
        """
        Auto-generate unique order number if not provided.
        
        NOTE: For production use, always use create_slaughter_order() service function
        which handles order number generation atomically with proper database locking.
        
        This method is kept for backward compatibility (admin panel, direct model creation)
        but delegates to the service layer for proper race condition handling.
        
        BUG FIX HISTORY:
        - (2026-01-08): Moved order number generation to service layer with select_for_update()
          to prevent race conditions in high-concurrency scenarios
        - (2026-02-27): order_datetime can be date or datetime; service layer handles both
        """
        if not self.slaughter_order_no:
            from .services import generate_order_number
            self.slaughter_order_no = generate_order_number(self.order_datetime)
        super().save(*args, **kwargs)

    def __str__(self):
        client_display = self.client.company_name if self.client else self.client_name
        order_date = self.order_datetime.date() if hasattr(self.order_datetime, 'date') else self.order_datetime
        return f"Order {self.slaughter_order_no} for {client_display} on {order_date}"
