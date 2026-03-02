"""
Model and service tests for the inventory app.

Note: The inventory app doesn't have URL routes configured yet.
These tests focus on model and service functionality.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import ServicePackage
from inventory.models import Carcass, MeatCut, Offal, StorageLocation
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()


class StorageLocationModelTest(TestCase):
    """Tests for StorageLocation model."""

    def test_create_storage_location(self):
        """Test creating a storage location."""
        location = StorageLocation.objects.create(name="Test Freezer", location_type="freezer")

        self.assertEqual(location.name, "Test Freezer")
        self.assertEqual(location.location_type, "freezer")

    def test_all_location_types(self):
        """Test all valid location types."""
        location_types = ["freezer", "cooler", "dry_storage", "processing"]

        for loc_type in location_types:
            location = StorageLocation.objects.create(name=f"{loc_type.title()} Location", location_type=loc_type)
            self.assertEqual(location.location_type, loc_type)

    def test_location_str_representation(self):
        """Test string representation of location."""
        location = StorageLocation.objects.create(name="Main Freezer", location_type="freezer")

        self.assertIn("Main Freezer", str(location))


class InventoryMovementTest(TestCase):
    """Tests for inventory movement between locations."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="inv_move_user", password="testpass123", role=User.Role.CLIENT)
        self.profile = ClientProfile.objects.create(
            user=self.user, account_type="INDIVIDUAL", phone_number="1234567890", address="Test Address"
        )
        self.service = ServicePackage.objects.create(name="Move Test Package", includes_disassembly=True)
        self.order = SlaughterOrder.objects.create(
            client=self.profile, order_datetime=timezone.now(), service_package=self.service
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order, animal_type="cattle", identification_tag="MOVE-TEST-001"
        )
        self.animal.perform_slaughter()
        self.animal.save()

        self.freezer = StorageLocation.objects.create(name="Test Freezer", location_type="freezer")
        self.cooler = StorageLocation.objects.create(name="Test Cooler", location_type="cooler")

    def test_move_carcass_between_locations(self):
        """Test moving a carcass between locations."""
        carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=Decimal("250.00"),
            disposition="for_sale",
            storage_location=self.freezer,
        )

        self.assertEqual(carcass.storage_location, self.freezer)

        # Move to cooler
        from inventory.services import move_inventory_item

        moved = move_inventory_item(carcass, self.cooler)

        self.assertEqual(moved.storage_location, self.cooler)

    def test_move_meat_cut(self):
        """Test moving a meat cut between locations."""
        carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=Decimal("250.00"),
            disposition="for_sale",
            storage_location=self.freezer,
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass,
            cut_type=MeatCut.BeefCuts.RIBEYE,
            weight=Decimal("10.0"),
            disposition="for_sale",
            storage_location=self.freezer,
        )

        from inventory.services import move_inventory_item

        moved = move_inventory_item(meat_cut, self.cooler)

        self.assertEqual(moved.storage_location, self.cooler)


class DispositionUpdateTest(TestCase):
    """Tests for updating inventory disposition."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="disp_test_user", password="testpass123", role=User.Role.CLIENT)
        self.profile = ClientProfile.objects.create(
            user=self.user, account_type="INDIVIDUAL", phone_number="1234567890", address="Test Address"
        )
        self.service = ServicePackage.objects.create(name="Disposition Test Package", includes_disassembly=True)
        self.order = SlaughterOrder.objects.create(
            client=self.profile, order_datetime=timezone.now(), service_package=self.service
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order, animal_type="cattle", identification_tag="DISP-TEST-001"
        )
        self.animal.perform_slaughter()
        self.animal.save()

    def test_update_carcass_disposition(self):
        """Test updating carcass disposition."""
        carcass = Carcass.objects.create(
            animal=self.animal, hot_carcass_weight=Decimal("250.00"), disposition="for_sale"
        )

        from inventory.services import update_inventory_disposition

        updated = update_inventory_disposition(carcass, "returned_to_owner")

        self.assertEqual(updated.disposition, "returned_to_owner")

    def test_all_disposition_types(self):
        """Test all valid disposition types."""
        carcass = Carcass.objects.create(
            animal=self.animal, hot_carcass_weight=Decimal("250.00"), disposition="for_sale"
        )

        from inventory.services import update_inventory_disposition

        for disposition in ["for_sale", "returned_to_owner", "disposed"]:
            updated = update_inventory_disposition(carcass, disposition)
            self.assertEqual(updated.disposition, disposition)


# ============================================================================
# Pytest-style tests
# ============================================================================


@pytest.mark.django_db
class TestInventoryQueries:
    """Pytest-style tests for inventory queries."""

    def test_get_inventory_by_location(self, animal_factory, service_package_factory):
        """Test getting inventory by location."""
        from inventory.services import get_inventory_by_location

        location = StorageLocation.objects.create(name="Query Test Location", location_type="freezer")

        service = service_package_factory()
        order = SlaughterOrder.objects.create(
            client_name="Test", service_package=service, order_datetime=timezone.now()
        )
        animal = animal_factory(slaughter_order=order)
        animal.perform_slaughter()
        animal.save()

        Carcass.objects.create(
            animal=animal, hot_carcass_weight=Decimal("200"), disposition="for_sale", storage_location=location
        )

        inventory = get_inventory_by_location(location)

        assert "carcasses" in inventory
        assert inventory["carcasses"].count() == 1

    def test_get_inventory_for_animal(self, animal_factory, service_package_factory):
        """Test getting all inventory items for an animal."""
        from inventory.services import get_inventory_for_animal

        service = service_package_factory()
        order = SlaughterOrder.objects.create(
            client_name="Test", service_package=service, order_datetime=timezone.now()
        )
        animal = animal_factory(slaughter_order=order)
        animal.perform_slaughter()
        animal.save()

        carcass = Carcass.objects.create(animal=animal, hot_carcass_weight=Decimal("200"), disposition="for_sale")

        Offal.objects.create(
            animal=animal, offal_type=Offal.BeefOffalTypes.LIVER, weight=Decimal("5"), disposition="for_sale"
        )

        inventory = get_inventory_for_animal(animal)

        assert inventory["carcass"] == carcass
        assert inventory["offal"].count() == 1


@pytest.mark.django_db
class TestStorageLocationTypes:
    """Tests for storage location types."""

    def test_location_types(self):
        """Test all valid location types."""
        location_types = ["freezer", "cooler", "dry_storage", "processing"]

        for loc_type in location_types:
            location = StorageLocation.objects.create(name=f"{loc_type.title()} Location", location_type=loc_type)
            assert location.location_type == loc_type
