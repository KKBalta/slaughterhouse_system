from django.contrib.auth.models import AbstractUser
from django.db import models
from core.models import BaseModel

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", 'Admin'
        CLERK = "CLERK", 'Clerk'
        CLIENT = "CLIENT", 'Client'

    base_role = Role.ADMIN

    role = models.CharField(max_length=50, choices=Role.choices)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.role = self.base_role
        return super().save(*args, **kwargs)

class ClientProfile(BaseModel):
    class AccountType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", 'Individual'
        ENTERPRISE = "ENTERPRISE", 'Enterprise'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client_profile')
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    
    # Fields for all account types
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20)
    address = models.TextField()

    # Enterprise-specific fields
    company_name = models.CharField(max_length=255, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)


    def __str__(self):
        if self.account_type == self.AccountType.ENTERPRISE:
            return f"{self.company_name} (Enterprise)"
        return f"{self.user.get_full_name()} (Individual)"
