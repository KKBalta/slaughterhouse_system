from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models

from core.models import BaseModel


class UserManager(DjangoUserManager):
    use_in_migrations = True

    def create_user(self, username, email=None, password=None, **extra_fields):
        role = (extra_fields.get("role") or "").strip()
        if not role:
            raise ValueError("create_user() requires an explicit role.")
        extra_fields["role"] = role
        return super().create_user(username=username, email=email, password=password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = self.model.Role.ADMIN
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return super().create_superuser(username=username, email=email, password=password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ADMIN = "ADMIN", "Admin"
        MANAGER = "MANAGER", "Manager"
        OPERATOR = "OPERATOR", "Operator"
        CLIENT = "CLIENT", "Client"
        WALKIN = "WALKIN", "Walk-in"

    role = models.CharField(max_length=50, choices=Role.choices)
    phone_number = models.CharField(max_length=20, blank=True, default="")
    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=models.Q(phone_number__gt=""),
                name="uniq_user_phone_nonempty",
            ),
        ]


class ClientProfile(BaseModel):
    class AccountType(models.TextChoices):
        UNCLASSIFIED = "UNCLASSIFIED", "Unclassified"
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        ENTERPRISE = "ENTERPRISE", "Enterprise"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="client_profile", null=True, blank=True
    )  # Made nullable for one-time clients
    account_type = models.CharField(max_length=20, choices=AccountType.choices)

    # Fields for all account types
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    default_destination = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Preferred delivery destination for this client. Used to prefill new orders.",
    )
    default_destination_client = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="source_clients",
        null=True,
        blank=True,
        help_text="Preferred destination client for this client. Used to prefill new orders.",
    )

    # Enterprise-specific fields
    company_name = models.CharField(max_length=255, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)

    def get_full_name(self):
        """Return the appropriate display name for the client."""
        if self.account_type == self.AccountType.ENTERPRISE:
            return self.company_name or "Unknown Company"
        if self.account_type == self.AccountType.INDIVIDUAL:
            if self.user:
                return self.user.get_full_name() or self.user.username
            return self.contact_person or "Unknown Individual"
        if self.user:
            return self.contact_person or self.company_name or self.user.get_full_name() or self.user.username
        return self.contact_person or self.company_name or "Unknown Walk-in"

    def __str__(self):
        if self.account_type == self.AccountType.ENTERPRISE:
            return f"{self.company_name} (Enterprise)"
        if self.account_type == self.AccountType.INDIVIDUAL:
            if self.user:
                return f"{self.user.get_full_name()} (Individual)"
            return f"{self.contact_person} (Individual)"
        return f"{self.get_full_name()} ({self.get_account_type_display()})"


CLIENT_MANAGEMENT_ROLES = (User.Role.CLIENT, User.Role.WALKIN)
