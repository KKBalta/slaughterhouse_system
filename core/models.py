import uuid
from django.db import models

class BaseModel(models.Model):
    """
    A comprehensive abstract base model with common fields.

    Includes:
    - A UUID primary key.
    - Automatic creation and update timestamps.
    - A soft-delete mechanism.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        """Marks the instance as inactive."""
        self.is_active = False
        self.save()

    def restore(self):
        """Marks the instance as active."""
        self.is_active = True
        self.save()
