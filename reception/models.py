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
        
        BUG FIX (2026-01-08):
        Previously used timezone.now() for the date string but order_datetime for counting,
        causing duplicate key violations when server timezone differed from order timezone.
        
        Example of the bug:
        - Order created on 2026-07-01 22:31 (local time, e.g., Turkey UTC+3)
        - Server timezone is UTC, so timezone.now() returns 2026-01-08 (UTC)
        - Order number generated: ORD-20260108-0012 (using server time)
        - But count uses order_datetime date (2026-07-01)
        - When creating 12th order on 2026-07-01, it tries ORD-20260108-0012 again → DUPLICATE ERROR
        
        Fix: Use order_datetime for both date string and count to ensure consistency.
        
        BUG FIX (2026-02-27):
        order_datetime can be passed as datetime.date (e.g. date.today() in tests).
        date objects have no .date() method - only datetime does. Handle both types.
        """
        if not self.slaughter_order_no:
            # Use order_datetime instead of timezone.now() to ensure consistency
            # This prevents timezone mismatches where server time differs from order time
            if self.order_datetime:
                # Handle both datetime (has .date()) and date (use as-is)
                order_date = self.order_datetime.date() if hasattr(self.order_datetime, 'date') else self.order_datetime
                date_str = order_date.strftime('%Y%m%d')
            else:
                # Fallback to current date if order_datetime is not set
                order_date = timezone.now().date()
                date_str = order_date.strftime('%Y%m%d')
            
            # Get the count of orders for the same date to make it unique
            # This approach is simple but might have race conditions in high-concurrency
            # For production, consider a more robust sequence generator or database sequence
            count = SlaughterOrder.objects.filter(order_datetime__date=order_date).count() + 1
            self.slaughter_order_no = f"ORD-{date_str}-{count:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        client_display = self.client.company_name if self.client else self.client_name
        order_date = self.order_datetime.date() if hasattr(self.order_datetime, 'date') else self.order_datetime
        return f"Order {self.slaughter_order_no} for {client_display} on {order_date}"
