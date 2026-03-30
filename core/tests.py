from django.db import IntegrityError
from django.test import TestCase
from django.utils.translation import activate, deactivate

from .default_service_packages import DEFAULT_SERVICE_PACKAGES, ensure_default_service_packages
from .models import ServicePackage


class CoreModelTest(TestCase):
    def test_service_package_soft_delete_restore(self):
        package = ServicePackage.objects.create(name="Test Package")
        self.assertTrue(package.is_active)

        package.soft_delete()
        package.refresh_from_db()
        self.assertFalse(package.is_active)

        package.restore()
        package.refresh_from_db()
        self.assertTrue(package.is_active)

    def test_create_service_package(self):
        package = ServicePackage.objects.create(
            name="Premium Package",
            description="Includes everything.",
            includes_disassembly=True,
            includes_delivery=True,
        )
        self.assertEqual(package.name, "Premium Package")
        self.assertTrue(package.includes_disassembly)
        self.assertTrue(package.includes_delivery)

    def test_service_package_name_uniqueness(self):
        ServicePackage.objects.create(name="Unique Package")
        with self.assertRaises(IntegrityError):
            ServicePackage.objects.create(name="Unique Package")

    def test_ensure_default_service_packages(self):
        ensure_default_service_packages()
        self.assertEqual(ServicePackage.objects.count(), 3)
        for spec in DEFAULT_SERVICE_PACKAGES:
            pkg = ServicePackage.objects.get(name=spec["name"])
            self.assertEqual(pkg.description, spec["description"])
            self.assertEqual(pkg.description_tr, spec["description_tr"])
            self.assertEqual(pkg.name_tr, spec["name_tr"])
            self.assertEqual(pkg.includes_disassembly, spec["includes_disassembly"])
            self.assertEqual(pkg.includes_delivery, spec["includes_delivery"])
        ensure_default_service_packages()
        self.assertEqual(ServicePackage.objects.count(), 3)

    def test_service_package_localized_name(self):
        package = ServicePackage.objects.create(name="Slaughter", name_tr="Kesim")
        self.assertEqual(package.localized_name(), "Slaughter")
        activate("tr")
        try:
            self.assertEqual(package.localized_name(), "Kesim")
        finally:
            deactivate()
