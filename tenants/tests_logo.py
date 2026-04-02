"""Tests for tenant logo upload path and company profile form validation."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tenants.forms import TenantCompanyProfileForm
from tenants.models import Client, tenant_logo_upload_to

try:
    from PIL import Image
except ImportError:
    Image = None


def test_path_uses_schema_and_slug_and_logo_suffix():
    inst = SimpleNamespace(
        schema_name="isim_et",
        company_name="İsim Et A.Ş.",
        name="Fallback",
    )
    path = tenant_logo_upload_to(inst, "brand.PNG")
    assert path == "tenant_logos/isim_et/isim-et-as_logo.png"


def test_unknown_extension_defaults_to_png():
    inst = SimpleNamespace(schema_name="acme", company_name="Acme", name="Acme")
    path = tenant_logo_upload_to(inst, "x.bmp")
    assert path == "tenant_logos/acme/acme_logo.png"


def test_empty_company_uses_schema_in_filename():
    inst = SimpleNamespace(schema_name="pomet", company_name="", name="")
    path = tenant_logo_upload_to(inst, "logo.jpg")
    assert path == "tenant_logos/pomet/pomet_logo.jpg"


@pytest.mark.django_db
def test_clean_logo_rejects_non_image_extension():
    client = Client(schema_name="testlogo", name="Test Co")
    client.save()
    upload = SimpleUploadedFile("evil.exe", b"x", content_type="application/octet-stream")
    form = TenantCompanyProfileForm(
        data={"name": "Test Co"},
        files={"logo": upload},
        instance=client,
    )
    assert not form.is_valid()
    assert "logo" in form.errors


@pytest.mark.django_db
def test_clean_logo_accepts_png():
    if Image is None:
        pytest.skip("Pillow is required for ImageField validation")
    buf = BytesIO()
    Image.new("RGB", (2, 2), color=(240, 240, 240)).save(buf, format="PNG")
    client = Client(schema_name="testlogo2", name="Test Co 2")
    client.save()
    upload = SimpleUploadedFile("x.png", buf.getvalue(), content_type="image/png")
    form = TenantCompanyProfileForm(
        data={
            "name": "Test Co 2",
            "company_name": "",
            "company_full_name": "",
            "company_address": "",
            "license_no": "",
            "operation_no": "",
            "contact_email": "",
            "contact_phone_area_code": "+90",
            "contact_phone": "",
            "printer_turkish_mode": "unicode",
        },
        files={"logo": upload},
        instance=client,
    )
    assert form.is_valid(), form.errors
