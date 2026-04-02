from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import override_settings
from django.urls import reverse

from tenants.models import TenantRegistrationRequest
from tenants.services import create_registration_request

pytestmark = pytest.mark.django_db


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True)
def test_public_signin_page_loads(client):
    response = client.get(reverse("public_signin"))
    assert response.status_code == 200
    assert b"public-signin-root" in response.content


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True)
def test_public_setup_post_creates_registration_and_redirects(client):
    response = client.post(
        reverse("public_setup"),
        data={
            "company_name": "Acme Meats",
            "owner_email": "owner@example.com",
            "owner_password": "StrongPass123!",
            "owner_password_confirm": "StrongPass123!",
            "company_full_name": "Acme Meats Incorporated",
        },
    )

    assert response.status_code == 302
    registration = TenantRegistrationRequest.objects.get(owner_email="owner@example.com")
    redirect = urlsplit(response["Location"])
    params = parse_qs(redirect.query)

    assert redirect.path == reverse("public_setup_status", args=[registration.id])
    assert "token" in params
    assert registration.status == TenantRegistrationRequest.Status.PENDING
    assert registration.company_name == "Acme Meats"


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True)
def test_public_setup_status_page_uses_status_payload(client):
    registration, token = create_registration_request(
        company_name="North Farm",
        owner_email="north@example.com",
        owner_password="StrongPass123!",
    )

    response = client.get(reverse("public_setup_status", args=[registration.id]), {"token": token})

    assert response.status_code == 200
    assert response.context["status_error"] == ""
    assert response.context["status_payload"]["status"] == TenantRegistrationRequest.Status.PENDING
    assert response.context["status_payload"]["derived_schema_preview"] == registration.derived_schema_name


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True)
def test_public_setup_status_page_shows_rejection_reason(client):
    registration, token = create_registration_request(
        company_name="Rejected Farm",
        owner_email="reject@example.com",
        owner_password="StrongPass123!",
    )
    registration.status = TenantRegistrationRequest.Status.REJECTED
    registration.rejection_reason = "Missing license details."
    registration.save(update_fields=["status", "rejection_reason", "updated_at"])

    response = client.get(reverse("public_setup_status", args=[registration.id]), {"token": token})

    assert response.status_code == 200
    assert response.context["status_payload"]["status"] == TenantRegistrationRequest.Status.REJECTED
    assert response.context["status_payload"]["rejection_reason"] == "Missing license details."


@override_settings(ROOT_URLCONF="config.urls_public", USE_MULTITENANT=True)
def test_public_setup_status_page_reports_missing_token(client):
    registration, _token = create_registration_request(
        company_name="Tokenless Farm",
        owner_email="tokenless@example.com",
        owner_password="StrongPass123!",
    )

    response = client.get(reverse("public_setup_status", args=[registration.id]))

    assert response.status_code == 200
    assert response.context["status_payload"] is None
    assert response.context["status_error"] == "Missing status token."
