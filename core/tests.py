from django.test import TestCase
from django.db import IntegrityError
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
            includes_delivery=True
        )
        self.assertEqual(package.name, "Premium Package")
        self.assertTrue(package.includes_disassembly)
        self.assertTrue(package.includes_delivery)

    def test_service_package_name_uniqueness(self):
        ServicePackage.objects.create(name="Unique Package")
        with self.assertRaises(IntegrityError):
            ServicePackage.objects.create(name="Unique Package")