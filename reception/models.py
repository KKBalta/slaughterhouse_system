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

    order_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    destination = models.CharField(
        max_length=255,
        blank=True, null=True,
        help_text="Specifies the final destination or market for the animals/products in this order."
    )

    def save(self, *args, **kwargs):
        if not self.slaughter_order_no:
            today = timezone.now().strftime('%Y%m%d')
            # Get the count of orders for today to make it unique
            # This approach is simple but might have race conditions in high-concurrency
            # For production, consider a more robust sequence generator or database sequence
            count = SlaughterOrder.objects.filter(order_date=self.order_date).count() + 1
            self.slaughter_order_no = f"ORD-{today}-{count:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        client_display = self.client.company_name if self.client else self.client_name
        return f"Order {self.slaughter_order_no} for {client_display} on {self.order_date}"
