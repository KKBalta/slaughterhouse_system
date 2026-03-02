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


class ServicePackage(BaseModel):
    """
    Defines a collection of services that a client can request.
    This model is crucial for enabling the modularity of the system, allowing different workflows based on selected services.
    """

    name = models.CharField(
        max_length=100, unique=True, help_text='A descriptive name for the service package (e.g., "Slaughter Only").'
    )
    description = models.TextField(blank=True, help_text="A detailed description of what the service package includes.")
    includes_disassembly = models.BooleanField(
        default=False, help_text="Indicates if this package includes the disassembly process."
    )
    includes_delivery = models.BooleanField(
        default=False, help_text="Indicates if this package includes delivery services."
    )
    # Add other boolean fields for specific services as needed

    def __str__(self):
        return self.name
