"""Discover-tenants API smoke tests (SQLite / settings_test)."""

import json

import pytest
from django.test import Client


@pytest.mark.django_db
def test_discover_tenants_not_multitenant_returns_400():
    """When USE_MULTITENANT is false, discovery returns 400 without importing tenant models."""
    client = Client()
    response = client.post(
        "/api/v1/auth/discover-tenants/",
        data=json.dumps({"email": "a@b.com"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "detail" in body
