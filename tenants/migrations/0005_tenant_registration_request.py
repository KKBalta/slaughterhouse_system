# Generated manually

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0004_email_tenant_membership"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantRegistrationRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("company_name", models.CharField(max_length=255)),
                ("company_full_name", models.CharField(blank=True, max_length=255)),
                ("company_address", models.CharField(blank=True, max_length=500)),
                ("license_no", models.CharField(blank=True, max_length=64)),
                ("operation_no", models.CharField(blank=True, max_length=64)),
                ("contact_phone", models.CharField(blank=True, max_length=64)),
                (
                    "derived_schema_name",
                    models.CharField(
                        db_index=True,
                        help_text="Candidate PostgreSQL schema / subdomain slug (from company name).",
                        max_length=63,
                    ),
                ),
                ("owner_email", models.EmailField(max_length=254)),
                ("owner_password_hash", models.CharField(max_length=128)),
                (
                    "status_token_hash",
                    models.CharField(
                        blank=True,
                        help_text="SHA-256 hex of opaque token for GET status (empty after rotate or if disabled).",
                        max_length=64,
                    ),
                ),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_tenant",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_registration",
                        to="tenants.client",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_tenant_registrations",
                        to="tenants.platformadmin",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_tenant_registration_request",
            },
        ),
        migrations.AddIndex(
            model_name="tenantregistrationrequest",
            index=models.Index(fields=["status", "created_at"], name="tenants_ten_status_d73870_idx"),
        ),
    ]
