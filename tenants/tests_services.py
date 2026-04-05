from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError

from tenants.models import Client, PlatformAdmin, TenantRegistrationRequest
from tenants.services import (
    allocate_unique_schema_name,
    approve_registration,
    create_registration_request,
    hard_delete_tenant,
    reject_registration,
    verify_status_token,
)

pytestmark = pytest.mark.django_db


def test_allocate_unique_schema_name_skips_existing_client_and_pending_request():
    Client.objects.create(schema_name="acme", name="Acme")
    TenantRegistrationRequest.objects.create(
        company_name="Pending Acme",
        derived_schema_name="acme-2",
        owner_email="pending@example.com",
        owner_password_hash="hashed-password",
    )

    assert allocate_unique_schema_name("acme") == "acme-3"


def test_create_registration_request_normalizes_fields_and_stores_token_hash():
    registration, raw_token = create_registration_request(
        company_name="  Acme Meat  ",
        owner_email=" OWNER@EXAMPLE.COM ",
        owner_password="testpass123",
        company_full_name="  Acme Meat LLC  ",
        company_address="  123 Test Street  ",
        license_no="  TR-42  ",
        operation_no="  OP-9  ",
        contact_phone="  +90 555 000 00 00  ",
    )

    assert registration.company_name == "Acme Meat"
    assert registration.company_full_name == "Acme Meat LLC"
    assert registration.company_address == "123 Test Street"
    assert registration.license_no == "TR-42"
    assert registration.operation_no == "OP-9"
    assert registration.contact_phone == "+90 555 000 00 00"
    assert registration.owner_email == "owner@example.com"
    assert registration.derived_schema_name == "acme-meat"
    assert registration.status == TenantRegistrationRequest.Status.PENDING
    assert registration.status_token_hash != raw_token
    assert len(registration.status_token_hash) == 64
    assert verify_status_token(registration.status_token_hash, raw_token) is True
    assert check_password("testpass123", registration.owner_password_hash) is True


def test_hard_delete_tenant_rejects_public_schema(mocker):
    mocker.patch("tenants.services.get_public_schema_name", return_value="public")

    with pytest.raises(ValidationError, match="public schema"):
        hard_delete_tenant(schema_name="public")


def test_hard_delete_tenant_rejects_reserved_schema(mocker):
    mocker.patch("tenants.services.get_public_schema_name", return_value="public")

    with pytest.raises(ValidationError, match="reserved"):
        hard_delete_tenant(schema_name="www")


def test_hard_delete_tenant_rejects_missing_tenant(mocker):
    mocker.patch("tenants.services.get_public_schema_name", return_value="public")

    with pytest.raises(ValidationError, match="Tenant not found"):
        hard_delete_tenant(schema_name="missing-tenant")


def test_hard_delete_tenant_deletes_existing_tenant(mocker):
    tenant = SimpleNamespace(pk=1)
    tenant.delete = mocker.Mock()
    fake_queryset = SimpleNamespace(first=lambda: tenant)

    mocker.patch("tenants.services.get_public_schema_name", return_value="public")
    mocker.patch("tenants.services.Client.objects.filter", return_value=fake_queryset)

    hard_delete_tenant(schema_name="acme")

    tenant.delete.assert_called_once_with(force_drop=True)


def test_approve_registration_returns_existing_approved_tenant():
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    tenant = Client.objects.create(schema_name="approved-tenant", name="Approved Tenant")
    registration = TenantRegistrationRequest.objects.create(
        company_name="Approved Co",
        derived_schema_name="approved-co",
        owner_email="owner@example.com",
        owner_password_hash="hashed-password",
        status=TenantRegistrationRequest.Status.APPROVED,
        approved_tenant=tenant,
    )

    assert approve_registration(registration, reviewer) == tenant


def test_approve_registration_rejects_non_pending_request():
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    registration = TenantRegistrationRequest.objects.create(
        company_name="Rejected Co",
        derived_schema_name="rejected-co",
        owner_email="owner@example.com",
        owner_password_hash="hashed-password",
        status=TenantRegistrationRequest.Status.REJECTED,
    )

    with pytest.raises(ValidationError, match="not pending"):
        approve_registration(registration, reviewer)


def test_approve_registration_creates_owner_user_and_marks_request_approved(mocker):
    user_model = get_user_model()
    user_model.objects.create_user(
        username="owner",
        email="someone-else@example.com",
        password="testpass123",
        role=user_model.Role.CLIENT,
    )
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    registration, _raw_token = create_registration_request(
        company_name="Acme Approval",
        owner_email="owner@example.com",
        owner_password="testpass123",
    )
    tenant = Client.objects.create(schema_name="acme-approval-live", name="Acme Approval")

    provision = mocker.patch("tenants.services.provision_tenant", return_value=tenant)
    mocker.patch("tenants.services.tenant_context", return_value=nullcontext())

    result = approve_registration(registration, reviewer)

    registration.refresh_from_db()
    created_user = user_model.objects.get(email="owner@example.com")

    assert result == tenant
    provision.assert_called_once()
    assert created_user.username == "owner-2"
    assert created_user.role == user_model.Role.OWNER
    assert created_user.is_staff is False
    assert created_user.is_superuser is False
    assert created_user.check_password("testpass123") is True
    assert registration.status == TenantRegistrationRequest.Status.APPROVED
    assert registration.reviewed_by == reviewer
    assert registration.approved_tenant == tenant
    assert registration.rejection_reason == ""
    assert registration.reviewed_at is not None


def test_approve_registration_cleans_up_provisioned_tenant_on_user_creation_error(mocker):
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    registration, _raw_token = create_registration_request(
        company_name="Broken Approval",
        owner_email="broken@example.com",
        owner_password="testpass123",
    )

    class ExplodingUser:
        class Role:
            OWNER = SimpleNamespace(value="OWNER")

        objects = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: False))

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def save(self):
            raise RuntimeError("boom")

    tenant = SimpleNamespace(pk=1)
    tenant.delete = mocker.Mock(side_effect=[TypeError("no force_drop"), None])

    mocker.patch("tenants.services.provision_tenant", return_value=tenant)
    mocker.patch("tenants.services.tenant_context", return_value=nullcontext())
    mocker.patch("tenants.services.get_user_model", return_value=ExplodingUser)

    with pytest.raises(RuntimeError, match="boom"):
        approve_registration(registration, reviewer)

    registration.refresh_from_db()
    assert registration.status == TenantRegistrationRequest.Status.PENDING
    assert tenant.delete.call_count == 2
    tenant.delete.assert_any_call(force_drop=True)
    tenant.delete.assert_any_call()


def test_reject_registration_marks_request_rejected():
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    registration = TenantRegistrationRequest.objects.create(
        company_name="Reject Me",
        derived_schema_name="reject-me",
        owner_email="owner@example.com",
        owner_password_hash="hashed-password",
    )

    reject_registration(registration, reviewer, reason="Missing paperwork")

    registration.refresh_from_db()
    assert registration.status == TenantRegistrationRequest.Status.REJECTED
    assert registration.reviewed_by == reviewer
    assert registration.rejection_reason == "Missing paperwork"
    assert registration.reviewed_at is not None


def test_reject_registration_rejects_non_pending_request():
    reviewer = PlatformAdmin.objects.create(email="reviewer@example.com", name="Reviewer")
    registration = TenantRegistrationRequest.objects.create(
        company_name="Already Approved",
        derived_schema_name="already-approved",
        owner_email="owner@example.com",
        owner_password_hash="hashed-password",
        status=TenantRegistrationRequest.Status.APPROVED,
    )

    with pytest.raises(ValidationError, match="not pending"):
        reject_registration(registration, reviewer, reason="Too late")
