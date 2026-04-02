import pytest
from django.db import IntegrityError
from django.utils.translation import activate, deactivate

from .default_service_packages import DEFAULT_SERVICE_PACKAGES, ensure_default_service_packages
from .models import ServicePackage

pytestmark = pytest.mark.django_db


def test_service_package_soft_delete_restore():
    package = ServicePackage.objects.create(name="Test Package")
    assert package.is_active

    package.soft_delete()
    package.refresh_from_db()
    assert not package.is_active

    package.restore()
    package.refresh_from_db()
    assert package.is_active


def test_create_service_package():
    package = ServicePackage.objects.create(
        name="Premium Package",
        description="Includes everything.",
        includes_disassembly=True,
        includes_delivery=True,
    )
    assert package.name == "Premium Package"
    assert package.includes_disassembly
    assert package.includes_delivery


def test_service_package_name_uniqueness():
    ServicePackage.objects.create(name="Unique Package")
    with pytest.raises(IntegrityError):
        ServicePackage.objects.create(name="Unique Package")


def test_ensure_default_service_packages():
    ensure_default_service_packages()
    assert ServicePackage.objects.count() == 3
    for spec in DEFAULT_SERVICE_PACKAGES:
        pkg = ServicePackage.objects.get(name=spec["name"])
        assert pkg.description == spec["description"]
        assert pkg.description_tr == spec["description_tr"]
        assert pkg.name_tr == spec["name_tr"]
        assert pkg.includes_disassembly == spec["includes_disassembly"]
        assert pkg.includes_delivery == spec["includes_delivery"]
    ensure_default_service_packages()
    assert ServicePackage.objects.count() == 3


def test_service_package_localized_name():
    package = ServicePackage.objects.create(name="Slaughter", name_tr="Kesim")
    assert package.localized_name() == "Slaughter"
    activate("tr")
    try:
        assert package.localized_name() == "Kesim"
    finally:
        deactivate()


def test_core_views_module_exposes_named_logger():
    from core import views

    assert views.logger.name == "core.views"
