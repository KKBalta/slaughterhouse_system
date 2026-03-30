"""Tenant registration slug helpers and API behavior."""

import json

import pytest
from django.test import Client, override_settings

from tenants.services import (
    RESERVED_SCHEMA_NAMES,
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
