from django.db import models
from core.models import BaseModel
from users.models import ClientProfile

class SlaughterOrder(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", 'Pending'
        IN_PROGRESS = "IN_PROGRESS", 'In Progress'
        COMPLETED = "COMPLETED", 'Completed'
        BILLED = "BILLED", 'Billed'

    # For registered clients
    client = models.ForeignKey(ClientProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='slaughter_orders')

    # For walk-in clients
    client_name = models.CharField(max_length=255, blank=True)
    client_phone = models.CharField(max_length=20, blank=True)

    order_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    def __str__(self):
        client_display = self.client.company_name if self.client else self.client_name
        return f"Order for {client_display} on {self.order_date}"

