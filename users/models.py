from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import BaseModel


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        MANAGER = "MANAGER", "Manager"
        OPERATOR = "OPERATOR", "Operator"
        CLIENT = "CLIENT", "Client"

    base_role = Role.ADMIN

    role = models.CharField(max_length=50, choices=Role.choices)

    def save(self, *args, **kwargs):
        if not self.pk and not self.role:
            self.role = self.base_role
        return super().save(*args, **kwargs)


class ClientProfile(BaseModel):
    class AccountType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        ENTERPRISE = "ENTERPRISE", "Enterprise"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="client_profile", null=True, blank=True
    )  # Made nullable for one-time clients
    account_type = models.CharField(max_length=20, choices=AccountType.choices)

    # Fields for all account types
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20)
    address = models.TextField()

    # Enterprise-specific fields
    company_name = models.CharField(max_length=255, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)

    def get_full_name(self):
        """Return the appropriate display name for the client."""
        if self.account_type == self.AccountType.ENTERPRISE:
            return self.company_name or "Unknown Company"
        else:
            if self.user:
                return self.user.get_full_name() or self.user.username
            return self.contact_person or "Unknown Individual"

    def __str__(self):
        if self.account_type == self.AccountType.ENTERPRISE:
            return f"{self.company_name} (Enterprise)"
        else:
            if self.user:
                return f"{self.user.get_full_name()} (Individual)"
            return f"{self.contact_person} (Individual)"
