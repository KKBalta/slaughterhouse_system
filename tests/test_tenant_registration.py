"""Tenant registration slug helpers and API behavior."""

import json

import pytest
from django.test import Client, override_settings

from tenants.models import Client as TenantClient, TenantRegistrationRequest
from tenants.registration_views import get_tenant_registration_status_payload
from tenants.services import (
    RESERVED_SCHEMA_NAMES,
    create_registration_request,
    derive_base_schema_name,
    is_valid_schema_slug,
)


def test_derive_base_schema_name_ascii_slug():
    assert derive_base_schema_name("Acme Gıda Sanayi A.Ş.") != ""
    assert "-" in derive_base_schema_name("Foo Bar Baz") or derive_base_schema_name("Foo Bar Baz").isalnum()


def test_reserved_schema_names():
    assert "public" in RESERVED_SCHEMA_NAMES
    assert not is_valid_schema_slug("public")
    assert not is_valid_schema_slug("")
    assert is_valid_schema_slug("acme-farm-1")


@pytest.mark.django_db
def test_tenant_registration_api_disabled_without_multitenant():
    """Registration endpoint returns 400 when USE_MULTITENANT is false (e.g. SQLite tests)."""
    client = Client()
    with override_settings(USE_MULTITENANT=False):
        response = client.post(
            "/api/v1/tenant-registration/",
            data=json.dumps(
                {
                    "company_name": "Test Co",
                    "owner_email": "a@b.com",
                    "owner_password": "testpass123",
                    "owner_password_confirm": "testpass123",
                }
            ),
            content_type="application/json",
        )
    assert response.status_code == 400
    assert "multi-tenant" in response.json().get("detail", "").lower()


@pytest.mark.django_db
def test_tenant_registration_api_returns_validation_errors_when_enabled(client, mocker):
    with override_settings(USE_MULTITENANT=True):
        mocker.patch("tenants.registration_views._rate_limited", return_value=False)
        response = client.post(
            "/api/v1/tenant-registration/",
            data=json.dumps(
                {
                    "company_name": "",
                    "owner_email": "not-an-email",
                    "owner_password": "testpass123",
                    "owner_password_confirm": "differentpass123",
                }
            ),
            content_type="application/json",
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == "Please correct the highlighted fields."
    assert "company_name" in payload["errors"]
    assert "owner_email" in payload["errors"]
    assert "owner_password_confirm" in payload["errors"]


@pytest.mark.django_db
def test_tenant_registration_api_returns_429_when_rate_limited(client, mocker):
    with override_settings(USE_MULTITENANT=True):
        mocker.patch("tenants.registration_views._rate_limited", return_value=True)
        response = client.post(
            "/api/v1/tenant-registration/",
            data=json.dumps(
                {
                    "company_name": "Rate Limited Co",
                    "owner_email": "owner@example.com",
                    "owner_password": "testpass123",
                    "owner_password_confirm": "testpass123",
                }
            ),
            content_type="application/json",
        )

    assert response.status_code == 429
    assert "too many" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_tenant_registration_api_creates_request_when_enabled(client, mocker):
    with override_settings(USE_MULTITENANT=True):
        mocker.patch("tenants.registration_views._rate_limited", return_value=False)
        response = client.post(
            "/api/v1/tenant-registration/",
            data=json.dumps(
                {
                    "company_name": "Acme Meat",
                    "owner_email": "OWNER@example.com",
                    "owner_password": "testpass123",
                    "owner_password_confirm": "testpass123",
                }
            ),
            content_type="application/json",
        )

    assert response.status_code == 201
    payload = response.json()
    registration = TenantRegistrationRequest.objects.get(pk=payload["id"])
    assert payload["status"] == TenantRegistrationRequest.Status.PENDING
    assert payload["derived_schema_preview"] == registration.derived_schema_name
    assert payload["status_token"]
    assert registration.owner_email == "owner@example.com"


@pytest.mark.django_db
def test_tenant_registration_status_api_accepts_bearer_token(client):
    registration, token = create_registration_request(
        company_name="Status Co",
        owner_email="owner@example.com",
        owner_password="testpass123",
    )

    with override_settings(USE_MULTITENANT=True):
        response = client.get(
            f"/api/v1/tenant-registration/{registration.pk}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(registration.pk),
        "status": TenantRegistrationRequest.Status.PENDING,
        "derived_schema_preview": registration.derived_schema_name,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query_string", "expected_status", "expected_detail"),
    [
        ("", 401, "Missing status token."),
        ("?token=wrong-token", 403, "Invalid token."),
    ],
)
def test_tenant_registration_status_api_rejects_missing_or_invalid_token(
    client, query_string, expected_status, expected_detail
):
    registration, _token = create_registration_request(
        company_name="Status Co",
        owner_email="owner@example.com",
        owner_password="testpass123",
    )

    with override_settings(USE_MULTITENANT=True):
        response = client.get(f"/api/v1/tenant-registration/{registration.pk}/{query_string}")

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


@pytest.mark.django_db
def test_get_tenant_registration_status_payload_includes_rejection_reason_and_schema_name():
    registration, token = create_registration_request(
        company_name="Payload Co",
        owner_email="owner@example.com",
        owner_password="testpass123",
    )

    registration.status = TenantRegistrationRequest.Status.REJECTED
    registration.rejection_reason = "Missing paperwork"
    registration.save(update_fields=["status", "rejection_reason", "updated_at"])

    rejected_payload = get_tenant_registration_status_payload(registration.pk, token)
    assert rejected_payload["rejection_reason"] == "Missing paperwork"

    tenant = TenantClient.objects.create(schema_name="payload-co-live", name="Payload Co")
    registration.status = TenantRegistrationRequest.Status.APPROVED
    registration.approved_tenant = tenant
    registration.rejection_reason = ""
    registration.save(update_fields=["status", "approved_tenant", "rejection_reason", "updated_at"])

    approved_payload = get_tenant_registration_status_payload(registration.pk, token)
    assert approved_payload["schema_name"] == tenant.schema_name
